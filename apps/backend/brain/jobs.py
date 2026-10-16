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

Step = Literal["reset", "prepare", "fetch", "ingest"]
_INGEST: tuple[Stage, ...] = ("records", "normalize", "load")  # repeated for each source
_STEP_STAGES: dict[Step, tuple[Stage, ...]] = {
    "reset": ("reset",),
    "prepare": ("prepare",),
    "fetch": ("fetch",),  # repeated for each source
    "ingest": _INGEST,
}


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

    @classmethod
    def of(cls, snap: BuildSnapshot) -> BuildSummary:
        stage = snap.events[-1].stage if snap.events else None
        return cls(state=snap.state, stage=stage, started_at=snap.started_at)


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
    plan: tuple[Stage, ...]
    step: Step | None = None  # the step `_execute` is in
    stop: threading.Event = field(default_factory=threading.Event)


@dataclass(eq=False)
class _Subscriber:
    slug: str | None  # None = every company
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[BuildEvent]


def _plan(kind: Kind, refetch: set[str] | None) -> tuple[Stage, ...]:
    """The stages a job goes through, in order."""
    first: tuple[Stage, ...] = ("reset", "prepare") if kind == "rebuild" else ("prepare",)
    fetch: tuple[Stage, ...] = ("fetch",) if refetch is None or refetch else ()
    return (*first, *fetch, *_INGEST)


def _after(plan: tuple[Stage, ...], last: BuildEvent) -> tuple[Stage, str | None]:
    """The stage (and source) that comes after `last` finished."""
    if last.status != "skipped" and last.stage in ("records", "normalize"):
        return _INGEST[_INGEST.index(last.stage) + 1], last.source  # same source, next stage
    if last.stage in _INGEST:
        return "records", None  # the next source
    if last.stage in plan[:-1]:
        return plan[plan.index(last.stage) + 1], None
    return last.stage, None


def _closing_event(
    snap: BuildSnapshot,
    status: Literal["failed", "stopped"],
    plan: tuple[Stage, ...],
    step: Step | None = None,
    message: str | None = None,
) -> BuildEvent | None:
    """The event that ends a failed or stopped job, on the stage (and source) that was in
    progress: never on a stage that already reported `done`. None when that stage already
    reported its own failure (pipeline.fetch does).

    - the last event is waiting/running: its stage was in progress;
    - a failure inside `step` before that step emitted anything: the step's first stage;
    - a failure in fetch between two sources: fetch, no source;
    - otherwise (a stop after a finished stage, or a restart): the stage after the last one.
    """
    last = snap.events[-1] if snap.events else None
    if last is None:
        stage, source = plan[0], None
    elif status == "failed" and last.status == "failed":
        return None
    elif last.status in ("waiting", "running"):
        stage, source = last.stage, last.source
    elif status == "failed" and step is not None and last.stage not in _STEP_STAGES[step]:
        stage, source = _STEP_STAGES[step][0], None
    elif status == "failed" and step == "fetch":
        stage, source = "fetch", None
    else:
        stage, source = _after(plan, last)
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
        # Validate everything before taking a slot, so a bad argument cannot leak one.
        snap = BuildSnapshot(slug=slug, kind=kind, state="queued", started_at=_now())
        keys = set(refetch) if refetch is not None else None
        job = _Job(snap, full, keys, _plan(kind, keys))
        with self._lock:
            current = self._jobs.get(slug)
            if current is not None and current.snapshot.state in ACTIVE:
                raise JobRunning(slug)
            has_slot = self._slots.acquire(blocking=False)
            try:
                if has_slot:
                    snap.state = "running"
                self._jobs[slug] = job
                self._emit(job, BuildEvent(slug, job.plan[0], "waiting"))
                worker = threading.Thread(
                    target=self._run, args=(job, has_slot), name=f"build-{slug}", daemon=True
                )
                worker.start()
            except BaseException as exc:
                if has_slot:
                    self._slots.release()
                if self._jobs.get(slug) is job:  # never runs: record it as failed, not running
                    error = str(exc) or type(exc).__name__
                    event = _closing_event(snap, "failed", job.plan, message=error)
                    self._finish(job, "failed", event, error)
                raise
            # Copied under the lock: the worker cannot change the snapshot until it is released.
            return snap.model_copy(deep=True)

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
                self._finish(job, "stopped", _closing_event(job.snapshot, "stopped", job.plan))
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
        return BuildSummary.of(snap) if snap is not None else None

    def subscribe(self, slug: str | None) -> Subscription:
        """Events of one company (or all, for None) from now on; nothing historical.

        Call it from the event loop that will iterate it. The queue is registered here, not on
        the first iteration, so no event emitted between this call and the first `anext` is
        lost. `aclose` it when done (iterated or not) so that it unregisters.
        """
        if slug is not None:
            self._path(slug)
        sub = _Subscriber(slug, asyncio.get_running_loop(), asyncio.Queue())
        with self._lock:
            self._subscribers.add(sub)
        return Subscription(self, sub)

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
                event = _closing_event(snap, "stopped", _plan(snap.kind, None))
                if event is not None:
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
                if job.snapshot.state == "stopped":  # stopped while queued; already recorded
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
                job.step = "reset"
                self._emit(job, BuildEvent(slug, "reset", "running"))
                self.steps.reset(slug)
                self._emit(job, BuildEvent(slug, "reset", "done"))
            check_stop()
            job.step = "prepare"
            self.steps.prepare(slug, on_event)
            if "fetch" in job.plan:
                check_stop()
                job.step = "fetch"
                self.steps.fetch(slug, job.refetch, on_event)
            check_stop()
            job.step = "ingest"
            report = self.steps.ingest(slug, job.full or snap.kind == "rebuild", on_event)
            totals = {"written": dict(report.load.written), "dropped": dict(report.load.dropped)}
            self._finish(job, "done", BuildEvent(slug, "done", "done", totals=totals))
        except BuildStopped:
            with self._lock:
                self._finish(job, "stopped", _closing_event(snap, "stopped", job.plan))
        except Exception as exc:
            log.exception("build of %s failed", slug)
            error = str(exc) or type(exc).__name__
            with self._lock:
                event = _closing_event(snap, "failed", job.plan, job.step, error)
                self._finish(job, "failed", event, error)

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
            elif snap.events:
                # The stage already reported its failure (pipeline.fetch does) before the state
                # changed. Subscribers read the state on each event, so send that one again.
                self._publish(snap.events[-1])

    def _publish(self, event: BuildEvent) -> None:
        for sub in list(self._subscribers):
            if sub.slug is not None and sub.slug != event.slug:
                continue
            try:
                sub.loop.call_soon_threadsafe(sub.queue.put_nowait, event)
            except RuntimeError:  # its event loop is closed: nobody is listening any more
                self._subscribers.discard(sub)

    def _unsubscribe(self, sub: _Subscriber) -> None:
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


class Subscription:
    """What `subscribe` returns: an endless async iterator of events. Not an async generator,
    because a generator that never started skips its `finally` on `aclose()`, which would
    leave the subscriber registered for good."""

    def __init__(self, runner: JobRunner, sub: _Subscriber):
        self._runner = runner
        self._sub = sub

    def __aiter__(self) -> Subscription:
        return self

    async def __anext__(self) -> BuildEvent:
        return await self._sub.queue.get()

    async def aclose(self) -> None:
        self._runner._unsubscribe(self._sub)


def _read(path: Path) -> BuildSnapshot | None:
    try:
        return BuildSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):  # ValidationError is a ValueError
        log.warning("unreadable build snapshot %s", path, exc_info=True)
        return None
