"""Build jobs: run a company's build in the background, report progress, allow a stop.

Why: a build (schema, fetch, ingest) takes minutes, so the API cannot run it inside a request.
The runner gives each company at most one job and runs at most `max_parallel` jobs at once (the
others wait in `queued`). Each job runs in a worker thread and records the pipeline's build
events in a snapshot. The snapshot is written to data/jobs/<slug>.json on every change, so the
last build of a company survives a server restart; `recover()` marks a build that was cut off by
a restart as `stopped`. Async subscribers (the SSE routes) get every event as it happens.

A stop sets a per-job flag; the runner's `on_event` wrapper raises `BuildStopped` at the next
event, and the runner checks the flag between steps. The pipeline itself knows nothing of jobs.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel

from brain import config, db, pipeline, schema
from brain.events import BuildEvent, BuildStopped, OnEvent, Stage

log = logging.getLogger(__name__)

Kind = Literal["build", "rebuild"]
State = Literal["queued", "running", "done", "failed", "stopped"]
ACTIVE: tuple[State, ...] = ("queued", "running")


def _now() -> str:
    return datetime.now(UTC).isoformat()


class BuildSnapshot(BaseModel):
    """One build of one company. The UI derives its stage table from `events`."""

    slug: str
    kind: Kind
    state: State
    started_at: str
    ended_at: str | None = None
    events: list[BuildEvent] = []
    error: str | None = None


class BuildSummary(BaseModel):
    """The short form the company list shows: state and the stage of the latest event."""

    state: State
    stage: Stage | None
    started_at: str


class JobRunning(Exception):
    def __init__(self, slug: str):
        super().__init__(f"A build for {slug} is already running")
        self.slug = slug


class Steps(Protocol):
    def reset(self, slug: str) -> None: ...
    def prepare(self, slug: str, on_event: OnEvent) -> None: ...
    def fetch(self, slug: str, keys: set[str] | None, on_event: OnEvent) -> None: ...
    def ingest(self, slug: str, full: bool, on_event: OnEvent) -> pipeline.IngestReport: ...


class PipelineSteps:
    """The real steps: drop the graph, apply the schema, fetch, ingest."""

    def reset(self, slug: str) -> None:
        db.delete_graph(slug)

    def prepare(self, slug: str, on_event: OnEvent) -> None:
        schema.apply_schema(slug, on_event=on_event)

    def fetch(self, slug: str, keys: set[str] | None, on_event: OnEvent) -> None:
        pipeline.fetch(slug, keys=keys, on_event=on_event)

    def ingest(self, slug: str, full: bool, on_event: OnEvent) -> pipeline.IngestReport:
        return pipeline.ingest(slug, full=full, on_event=on_event)


@dataclass(eq=False)
class _Job:
    snapshot: BuildSnapshot
    full: bool
    refetch: set[str] | None
    stop: threading.Event = field(default_factory=threading.Event)


@dataclass(eq=False)
class _Subscriber:
    slug: str | None  # None = every company
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[BuildEvent]


def _closing_event(
    snap: BuildSnapshot, status: Literal["failed", "stopped"], message: str | None = None
) -> BuildEvent | None:
    """The event that ends a failed or stopped job, on the stage (and source) that was running.
    None when that stage already reported its own failure (pipeline.fetch does)."""
    last = snap.events[-1] if snap.events else None
    if last is not None and status == "failed" and last.status == "failed":
        return None
    stage = last.stage if last is not None else "prepare"
    source = last.source if last is not None else None
    return BuildEvent(snap.slug, stage, status, source, message=message)


class JobRunner:
    def __init__(
        self, max_parallel: int = 2, steps: Steps | None = None, jobs_dir: Path | None = None
    ):
        self.steps: Steps = steps or PipelineSteps()
        self._jobs_dir = jobs_dir
        self._slots = threading.Semaphore(max_parallel)
        # One lock for the job table, every snapshot change, its file and the subscriber set.
        self._lock = threading.RLock()
        self._jobs: dict[str, _Job] = {}  # latest job per slug started by this process
        self._subscribers: set[_Subscriber] = set()

    # --- public API ----------------------------------------------------------------------------

    def start(
        self,
        slug: str,
        kind: Kind = "build",
        full: bool = False,
        refetch: set[str] | None = None,
    ) -> BuildSnapshot:
        """Start a job. build: prepare -> fetch -> ingest(full). rebuild: reset -> prepare ->
        fetch -> ingest(full=True). Fetch takes only the `refetch` keys (None = every source)
        and is skipped when `refetch` is empty. Raises JobRunning if the slug has a job."""
        self._path(slug)  # validates the slug
        with self._lock:
            current = self._jobs.get(slug)
            if current is not None and current.snapshot.state in ACTIVE:
                raise JobRunning(slug)
            has_slot = self._slots.acquire(blocking=False)
            snap = BuildSnapshot(
                slug=slug,
                kind=kind,
                state="running" if has_slot else "queued",
                started_at=_now(),
            )
            job = _Job(snap, full, set(refetch) if refetch is not None else None)
            self._jobs[slug] = job
            first: Stage = "reset" if kind == "rebuild" else "prepare"
            self._emit(job, BuildEvent(slug, first, "waiting"))
            result = snap.model_copy(deep=True)
        worker = threading.Thread(
            target=self._run, args=(job, has_slot), name=f"build-{slug}", daemon=True
        )
        worker.start()
        return result

    def stop(self, slug: str) -> bool:
        """Ask the slug's job to stop. A queued job stops at once; a running one at its next
        event or step. False when the slug has no queued or running job."""
        self._path(slug)
        with self._lock:
            job = self._jobs.get(slug)
            if job is None or job.snapshot.state not in ACTIVE:
                return False
            job.stop.set()
            if job.snapshot.state == "queued":
                self._finish(job, "stopped", _closing_event(job.snapshot, "stopped"))
            return True

    def current(self, slug: str) -> BuildSnapshot | None:
        """The slug's job from this process, else its last snapshot on disk, else None."""
        path = self._path(slug)
        with self._lock:
            job = self._jobs.get(slug)
            if job is not None:
                return job.snapshot.model_copy(deep=True)
        return _read(path)

    def summary(self, slug: str) -> BuildSummary | None:
        snap = self.current(slug)
        if snap is None:
            return None
        stage = snap.events[-1].stage if snap.events else None
        return BuildSummary(state=snap.state, stage=stage, started_at=snap.started_at)

    def subscribe(self, slug: str | None) -> AsyncIterator[BuildEvent]:
        """Events of one company (or all, for None) from now on; nothing historical.

        Call it from the event loop that will iterate it. The queue is registered here, not on
        the first iteration, so no event emitted between this call and the first `anext` is
        lost. Iterate it (or `aclose` it after starting) so that it unregisters.
        """
        if slug is not None:
            self._path(slug)
        sub = _Subscriber(slug, asyncio.get_running_loop(), asyncio.Queue())
        with self._lock:
            self._subscribers.add(sub)
        return self._drain(sub)

    def recover(self) -> None:
        """On startup: a snapshot still `queued`/`running` belonged to a process that is gone."""
        jobs_dir = self.jobs_dir
        if not jobs_dir.is_dir():
            return
        for path in sorted(jobs_dir.glob("*.json")):
            slug = path.stem
            if not re.fullmatch(config.SLUG_RE, slug):
                continue
            with self._lock:
                if slug in self._jobs:
                    continue
                snap = _read(path)
                if snap is None or snap.state not in ACTIVE:
                    continue
                if (event := _closing_event(snap, "stopped")) is not None:
                    snap.events.append(event)
                snap.state = "stopped"
                snap.ended_at = _now()
                self._persist(snap)

    @property
    def jobs_dir(self) -> Path:
        return self._jobs_dir or config.REPO_ROOT / "data" / "jobs"

    # --- worker --------------------------------------------------------------------------------

    def _run(self, job: _Job, has_slot: bool) -> None:
        if not has_slot:
            self._slots.acquire()  # wait in `queued` for a free slot
        try:
            with self._lock:
                if job.stop.is_set():  # stopped while queued; already recorded
                    return
                if job.snapshot.state == "queued":
                    job.snapshot.state = "running"
                    self._persist(job.snapshot)
            self._execute(job)
        finally:
            self._slots.release()

    def _execute(self, job: _Job) -> None:
        snap = job.snapshot
        slug = snap.slug

        def check_stop() -> None:
            if job.stop.is_set():
                raise BuildStopped

        def on_event(event: BuildEvent) -> None:
            self._emit(job, event)
            check_stop()

        try:
            if snap.kind == "rebuild":
                check_stop()
                self._emit(job, BuildEvent(slug, "reset", "running"))
                self.steps.reset(slug)
                self._emit(job, BuildEvent(slug, "reset", "done"))
            check_stop()
            self.steps.prepare(slug, on_event)
            if job.refetch is None or job.refetch:
                check_stop()
                self.steps.fetch(slug, job.refetch, on_event)
            check_stop()
            report = self.steps.ingest(slug, job.full or snap.kind == "rebuild", on_event)
            totals = {"written": dict(report.load.written), "dropped": dict(report.load.dropped)}
            self._finish(job, "done", BuildEvent(slug, "done", "done", totals=totals))
        except BuildStopped:
            with self._lock:
                self._finish(job, "stopped", _closing_event(snap, "stopped"))
        except Exception as exc:
            log.exception("build of %s failed", slug)
            error = str(exc) or type(exc).__name__
            with self._lock:
                self._finish(job, "failed", _closing_event(snap, "failed", error), error)

    # --- snapshot and delivery (callers may or may not hold the lock; it is reentrant) --------

    def _emit(self, job: _Job, event: BuildEvent) -> None:
        with self._lock:
            job.snapshot.events.append(event)
            self._persist(job.snapshot)
            self._publish(event)

    def _finish(
        self, job: _Job, state: State, event: BuildEvent | None, error: str | None = None
    ) -> None:
        with self._lock:
            snap = job.snapshot
            # State first, so a subscriber reading `current()` on the last event sees it.
            snap.state = state
            snap.ended_at = _now()
            snap.error = error
            if event is not None:
                snap.events.append(event)
            self._persist(snap)
            if event is not None:
                self._publish(event)

    def _publish(self, event: BuildEvent) -> None:
        for sub in list(self._subscribers):
            if sub.slug is not None and sub.slug != event.slug:
                continue
            try:
                sub.loop.call_soon_threadsafe(sub.queue.put_nowait, event)
            except RuntimeError:  # its event loop is closed: nobody is listening any more
                self._subscribers.discard(sub)

    async def _drain(self, sub: _Subscriber) -> AsyncIterator[BuildEvent]:
        try:
            while True:
                yield await sub.queue.get()
        finally:
            with self._lock:
                self._subscribers.discard(sub)

    def _persist(self, snap: BuildSnapshot) -> None:
        """Replace data/jobs/<slug>.json atomically. A failed write is logged, not raised: the
        build itself must not fail because its progress file could not be written."""
        path = self._path(snap.slug)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(snap.model_dump_json())
                os.chmod(tmp_name, 0o644)  # mkstemp creates 0600
                os.replace(tmp_name, path)
            finally:
                Path(tmp_name).unlink(missing_ok=True)
        except OSError:
            log.exception("could not write build snapshot %s", path)

    def _path(self, slug: str) -> Path:
        if not re.fullmatch(config.SLUG_RE, slug):  # also keeps "../x" out of the folder
            raise ValueError(f"invalid company slug: {slug!r}")
        return self.jobs_dir / f"{slug}.json"


def _read(path: Path) -> BuildSnapshot | None:
    try:
        return BuildSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):  # ValidationError is a ValueError
        log.warning("unreadable build snapshot %s", path, exc_info=True)
        return None
