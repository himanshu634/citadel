"""Build job runner: one job per company, two at once, stoppable, persisted per company."""

from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest
from brain import config, db, registry
from brain.events import BuildEvent
from brain.jobs import BuildSnapshot, JobRunner, JobRunning, PipelineSteps
from brain.loader import LoadReport
from brain.pipeline import IngestReport
from conftest import needs_graph, synthetic_company

TERMINAL = {"done", "failed", "stopped"}

RUNNING_SNAPSHOT = {
    "slug": "a",
    "kind": "build",
    "state": "running",
    "started_at": "2026-10-16T10:00:00+00:00",
    "ended_at": None,
    "events": [
        {
            "slug": "a",
            "stage": "fetch",
            "status": "running",
            "source": "github:acme/widgets",
            "at": "2026-10-16T10:00:01+00:00",
        }
    ],
    "error": None,
}


SRC = "github:acme/widgets"

# The events each fake step emits, in the order the real pipeline emits them.
STEP_EVENTS = {
    "prepare": [("prepare", "running", None), ("prepare", "done", None)],
    "fetch": [("fetch", "running", SRC), ("fetch", "done", SRC)],
    "ingest": [
        ("records", "running", SRC),
        ("records", "done", SRC),
        ("normalize", "done", SRC),
        ("load", "running", SRC),
        ("load", "done", SRC),
    ],
}


class FakeSteps:
    """Records calls and emits the real pipeline's events. `gate` (when given) blocks `prepare`
    after `gate_at` of its events until the test sets it. `fail_on` makes that step raise after
    `fail_after` of its events (default: before its last one)."""

    def __init__(
        self,
        gate: threading.Event | None = None,
        gate_at: int = 1,
        fail_on: str | None = None,
        fail_after: int | None = None,
    ):
        self.gate = gate
        self.gate_at = gate_at
        self.fail_on = fail_on
        self.fail_after = fail_after
        self.calls: list[str] = []

    def _step(self, name, slug, on_event):
        events = STEP_EVENTS[name]
        fail_at = len(events) - 1 if self.fail_after is None else self.fail_after
        for i, (stage, status, source) in enumerate(events):
            if name == self.fail_on and i == fail_at:
                raise RuntimeError("boom")
            if name == "prepare" and self.gate is not None and i == self.gate_at:
                assert self.gate.wait(5), "test never opened the gate"
            on_event(BuildEvent(slug, stage, status, source))
        if name == "prepare" and self.gate is not None and self.gate_at == len(events):
            assert self.gate.wait(5), "test never opened the gate"

    def reset(self, slug):
        self.calls.append("reset")
        if self.fail_on == "reset":
            raise RuntimeError("boom")

    def prepare(self, slug, on_event):
        self.calls.append("prepare")
        self._step("prepare", slug, on_event)

    def fetch(self, slug, keys, on_event):
        self.calls.append(f"fetch({sorted(keys) if keys is not None else None})")
        self._step("fetch", slug, on_event)

    def ingest(self, slug, full, on_event):
        self.calls.append(f"ingest(full={full})")
        self._step("ingest", slug, on_event)
        report = IngestReport()
        report.load = LoadReport()
        report.load.written["load/person"] = 3
        return report


def pairs(snap: BuildSnapshot, n: int) -> list[tuple]:
    """The last n events as (stage, status, source)."""
    return [(e.stage, e.status, e.source) for e in snap.events[-n:]]


def wait_done(runner: JobRunner, slug: str, timeout: float = 5) -> BuildSnapshot:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = runner.current(slug)
        if snap is not None and snap.state in TERMINAL:
            return snap
        time.sleep(0.01)
    raise AssertionError(f"job {slug} did not finish: {runner.current(slug)}")


@pytest.fixture
def gate():
    g = threading.Event()
    yield g
    g.set()  # never leave a worker blocked


@pytest.fixture
def runner(tmp_path, gate):
    return JobRunner(steps=FakeSteps(gate=gate), jobs_dir=tmp_path)


@pytest.fixture
def runner_recording(tmp_path):
    return JobRunner(steps=FakeSteps(), jobs_dir=tmp_path)


@pytest.fixture
def runner_failing(tmp_path):
    return JobRunner(steps=FakeSteps(fail_on="ingest"), jobs_dir=tmp_path)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_second_start_same_slug_raises(runner, gate):
    runner.start("a")
    with pytest.raises(JobRunning):
        runner.start("a")


def test_concurrent_starts_same_slug_only_one_wins(runner, gate):
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def go():
        barrier.wait()
        try:
            runner.start("a")
            outcomes.append("started")
        except JobRunning:
            outcomes.append("refused")

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert sorted(outcomes) == ["refused", "started"]


def test_third_company_queues(runner, gate):
    assert runner.start("a").state == "running"
    assert runner.start("b").state == "running"
    assert runner.start("c").state == "queued"
    gate.set()
    wait_done(runner, "c")
    assert runner.current("c").state == "done"


def test_build_order_and_totals(runner_recording):
    runner_recording.start("a", full=True)
    snap = wait_done(runner_recording, "a")
    assert runner_recording.steps.calls == ["prepare", "fetch(None)", "ingest(full=True)"]
    assert snap.state == "done" and snap.ended_at and snap.error is None
    last = snap.events[-1]
    assert (last.stage, last.status) == ("done", "done")
    assert last.totals == {"written": {"load/person": 3}, "dropped": {}}


def test_build_fetches_only_refetch_keys(runner_recording):
    runner_recording.start("a", refetch={"github:acme/new"})
    wait_done(runner_recording, "a")
    assert runner_recording.steps.calls == [
        "prepare",
        "fetch(['github:acme/new'])",
        "ingest(full=False)",
    ]


def test_rebuild_order(runner_recording):
    runner_recording.start("a", kind="rebuild", refetch=set())
    snap = wait_done(runner_recording, "a")
    assert runner_recording.steps.calls == ["reset", "prepare", "ingest(full=True)"]
    assert [(e.stage, e.status) for e in snap.events[:3]] == [
        ("reset", "waiting"),
        ("reset", "running"),
        ("reset", "done"),
    ]


def test_rebuild_fetches_refetch_keys(runner_recording):
    runner_recording.start("a", kind="rebuild", refetch={"github:acme/widgets"})
    wait_done(runner_recording, "a")
    assert runner_recording.steps.calls == [
        "reset",
        "prepare",
        "fetch(['github:acme/widgets'])",
        "ingest(full=True)",
    ]


def test_stop(runner, gate):
    runner.start("a")
    assert runner.stop("a") is True
    gate.set()
    snap = wait_done(runner, "a")
    assert snap.state == "stopped"
    last = snap.events[-1]
    assert last.status == "stopped"
    finished = {(e.stage, e.source) for e in snap.events if e.status == "done"}
    assert (last.stage, last.source) not in finished  # never on a stage that finished
    assert runner.steps.calls in ([], ["prepare"])  # nothing after the stop


def test_stop_before_the_worker_starts(runner):
    with runner._lock:  # the worker cannot begin until both calls are done
        assert runner.start("a").state == "running"
        assert runner.stop("a") is True
    snap = wait_done(runner, "a")
    assert snap.state == "stopped"
    assert pairs(snap, 2) == [("prepare", "waiting", None), ("prepare", "stopped", None)]
    assert runner.steps.calls == []


def test_stop_after_a_finished_stage_lands_on_the_next(tmp_path, gate):
    r = JobRunner(steps=FakeSteps(gate=gate, gate_at=2), jobs_dir=tmp_path)
    r.start("a")
    deadline = time.monotonic() + 5
    while pairs(r.current("a"), 1) != [("prepare", "done", None)]:
        assert time.monotonic() < deadline, r.current("a")
        time.sleep(0.01)
    r.stop("a")
    gate.set()
    snap = wait_done(r, "a")
    assert pairs(snap, 2) == [("prepare", "done", None), ("fetch", "stopped", None)]
    assert r.steps.calls == ["prepare"]


def test_stop_queued_job_never_runs(runner, gate):
    runner.start("a")
    runner.start("b")
    assert runner.start("c").state == "queued"
    assert runner.stop("c") is True
    assert runner.current("c").state == "stopped"
    gate.set()
    wait_done(runner, "a")
    wait_done(runner, "b")
    assert runner.steps.calls.count("prepare") == 2  # a and b only
    assert runner.current("c").state == "stopped"


def test_stop_without_job_is_false(runner):
    assert runner.stop("a") is False


def test_failed_step_records_error(runner_failing):
    runner_failing.start("a")
    snap = wait_done(runner_failing, "a")
    assert snap.state == "failed" and "boom" in snap.error
    assert pairs(snap, 2) == [("load", "running", SRC), ("load", "failed", SRC)]
    assert snap.events[-1].message == "boom"


def test_failure_before_a_step_emits_lands_on_its_first_stage(tmp_path):
    r = JobRunner(steps=FakeSteps(fail_on="ingest", fail_after=0), jobs_dir=tmp_path)
    r.start("a")
    snap = wait_done(r, "a")
    assert snap.state == "failed"
    assert pairs(snap, 2) == [("fetch", "done", SRC), ("records", "failed", None)]


def test_failure_between_ingest_stages_lands_on_the_next(tmp_path):
    # e.g. loader.get_cursor or normalize raising after `records done`
    r = JobRunner(steps=FakeSteps(fail_on="ingest", fail_after=2), jobs_dir=tmp_path)
    r.start("a")
    snap = wait_done(r, "a")
    assert pairs(snap, 2) == [("records", "done", SRC), ("normalize", "failed", SRC)]


def test_failure_before_prepare_emits(tmp_path):
    r = JobRunner(steps=FakeSteps(fail_on="prepare", fail_after=0), jobs_dir=tmp_path)
    r.start("a")
    snap = wait_done(r, "a")
    assert pairs(snap, 2) == [("prepare", "waiting", None), ("prepare", "failed", None)]


def test_invalid_arguments_do_not_leak_a_slot(tmp_path, gate):
    r = JobRunner(max_parallel=1, steps=FakeSteps(gate=gate), jobs_dir=tmp_path)
    for _ in range(2):
        with pytest.raises(ValueError):
            r.start("a", kind="Build")
        with pytest.raises(TypeError):
            r.start("a", refetch=5)
    assert r.current("a") is None
    assert r.start("a").state == "running"


def test_thread_start_failure_releases_slot_and_fails_job(tmp_path, gate, monkeypatch):
    r = JobRunner(max_parallel=1, steps=FakeSteps(gate=gate), jobs_dir=tmp_path)

    def no_threads(self):
        raise RuntimeError("can't start new thread")

    with monkeypatch.context() as m:
        m.setattr(threading.Thread, "start", no_threads)
        with pytest.raises(RuntimeError):
            r.start("a")
    snap = r.current("a")
    assert snap.state == "failed" and "can't start new thread" in snap.error
    assert r.start("a").state == "running"  # not JobRunning, and the slot is free


def test_failed_reset_is_reported_on_reset(tmp_path):
    r = JobRunner(steps=FakeSteps(fail_on="reset"), jobs_dir=tmp_path)
    r.start("a", kind="rebuild", refetch=set())
    snap = wait_done(r, "a")
    assert snap.state == "failed"
    assert (snap.events[-1].stage, snap.events[-1].status) == ("reset", "failed")


def test_failed_job_can_start_again(runner_failing):
    runner_failing.start("a")
    wait_done(runner_failing, "a")
    runner_failing.steps.fail_on = None
    runner_failing.start("a")
    assert wait_done(runner_failing, "a").state == "done"


def test_snapshot_is_persisted(runner_recording, tmp_path):
    runner_recording.start("a")
    snap = wait_done(runner_recording, "a")
    path = tmp_path / "a.json"
    assert path.stat().st_mode & 0o777 == 0o644
    assert BuildSnapshot.model_validate_json(path.read_text()) == snap
    assert not list(tmp_path.glob(".*"))  # no temp files left behind
    fresh = JobRunner(steps=FakeSteps(), jobs_dir=tmp_path)
    assert fresh.current("a") == snap


def test_current_without_any_job_is_none(runner):
    assert runner.current("a") is None
    assert runner.summary("a") is None


def test_summary(runner, gate):
    runner.start("a")
    deadline = time.monotonic() + 5
    while runner.summary("a").stage != "prepare" and time.monotonic() < deadline:
        time.sleep(0.01)
    s = runner.summary("a")
    assert (s.state, s.stage) == ("running", "prepare") and s.started_at


def test_jobs_dir_defaults_under_repo_root(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    r = JobRunner(steps=FakeSteps())
    r.start("a")
    wait_done(r, "a")
    assert (tmp_path / "data" / "jobs" / "a.json").is_file()


def test_invalid_slug_is_refused(runner):
    with pytest.raises(ValueError):
        runner.start("../x")
    with pytest.raises(ValueError):
        runner.current("../x")


def test_restart_marks_running_as_stopped(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(RUNNING_SNAPSHOT))
    r = JobRunner(jobs_dir=tmp_path, steps=FakeSteps())
    r.recover()
    snap = r.current("a")
    assert snap.state == "stopped" and snap.ended_at
    assert (snap.events[-1].stage, snap.events[-1].status) == ("fetch", "stopped")
    assert json.loads((tmp_path / "a.json").read_text())["state"] == "stopped"
    r.start("a")  # does not raise
    assert wait_done(r, "a").state == "done"


def test_restart_after_a_finished_stage_marks_the_next_stopped(tmp_path):
    snap = {**RUNNING_SNAPSHOT, "events": [{"slug": "a", "stage": "prepare", "status": "done"}]}
    (tmp_path / "a.json").write_text(json.dumps(snap))
    r = JobRunner(jobs_dir=tmp_path, steps=FakeSteps())
    r.recover()
    assert pairs(r.current("a"), 1) == [("fetch", "stopped", None)]


@pytest.mark.anyio
async def test_subscribe_gets_events(runner, gate):
    it = runner.subscribe("a")
    runner.start("a")
    first = await asyncio.wait_for(anext(it), 2)
    assert (first.slug, first.stage, first.status) == ("a", "prepare", "waiting")
    second = await asyncio.wait_for(anext(it), 2)
    assert (second.stage, second.status) == ("prepare", "running")
    await it.aclose()


@pytest.mark.anyio
async def test_subscribe_all_and_other_slug(runner, gate):
    every = runner.subscribe(None)
    other = runner.subscribe("b")
    runner.start("a")
    assert (await asyncio.wait_for(anext(every), 2)).slug == "a"
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(other), 0.2)
    await every.aclose()
    await other.aclose()
    assert not runner._subscribers  # closed iterators unregister


# --- real pipeline steps on a throwaway company ------------------------------------------------

REBUILD_SLUG = "test_rebuild"


class FailIngestOnce(PipelineSteps):
    def __init__(self):
        self.failures_left = 0

    def ingest(self, slug, full, on_event):
        if self.failures_left:
            self.failures_left -= 1
            raise RuntimeError("boom")
        return super().ingest(slug, full, on_event)


@pytest.fixture
def rebuild_company(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    (tmp_path / "companies").mkdir()
    registry.write_new(synthetic_company(REBUILD_SLUG))
    db.delete_graph(REBUILD_SLUG)
    yield REBUILD_SLUG
    db.delete_graph(REBUILD_SLUG)


def _synced_sources(slug: str) -> list:
    return db.run(slug, "load/sync_state_latest", read_only=True)[0]["sources"]


@needs_graph
def test_rebuild_failure_after_reset_leaves_failed_and_retry_works(rebuild_company, tmp_path):
    steps = FailIngestOnce()
    r = JobRunner(steps=steps, jobs_dir=tmp_path / "jobs")
    r.start(rebuild_company)
    assert wait_done(r, rebuild_company, 30).state == "done"
    assert _synced_sources(rebuild_company)

    steps.failures_left = 1
    r.start(rebuild_company, kind="rebuild", refetch=set())
    snap = wait_done(r, rebuild_company, 30)
    assert snap.state == "failed" and "boom" in snap.error
    # reset wiped the old data; prepare re-created the graph with indexes only
    assert not _synced_sources(rebuild_company)
    assert registry.exists(rebuild_company)  # the config is untouched

    r.start(rebuild_company)
    assert wait_done(r, rebuild_company, 30).state == "done"
    assert _synced_sources(rebuild_company)
