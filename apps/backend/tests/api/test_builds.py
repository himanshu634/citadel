"""Build routes, their SSE streams, and the Settings save (PUT) that can start a rebuild."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time

import pytest
from backend import config_diff
from backend.api import builds, create_app
from backend.jobs import BuildSnapshot, JobRunner
from backend.testing import FakeSteps
from brain import config
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from .conftest import write

TERMINAL = {"done", "failed", "stopped"}


@pytest.fixture
def company(api_root):
    write(api_root, "acme_labs", name="Acme Labs")
    return "acme_labs"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def current_config(client, slug: str) -> dict:
    return client.get(f"/api/companies/{slug}").json()["config"]


def with_since(cfg: dict, since: str) -> dict:
    return {**cfg, "window": {**cfg["window"], "since": since}}


def yaml_text(slug: str) -> str:
    return (config.companies_dir() / f"{slug}.yaml").read_text()


def wait_done(runner: JobRunner, slug: str, timeout: float = 5) -> BuildSnapshot:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = runner.current(slug)
        if snap is not None and snap.state in TERMINAL:
            return snap
        time.sleep(0.01)
    raise AssertionError(f"job {slug} did not finish: {runner.current(slug)}")


def sse(lines) -> list[tuple[str, dict]]:
    """(event, data) pairs from an SSE response's lines."""
    out: list[tuple[str, dict]] = []
    name = None
    for line in lines:
        if line.startswith("event:"):
            name = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            out.append((name, json.loads(line.removeprefix("data:").strip())))
    return out


# --- start, inspect, stop --------------------------------------------------------------------


def test_double_start_is_409(client, company):
    assert client.post(f"/api/companies/{company}/builds", json={}).status_code == 202
    r = client.post(f"/api/companies/{company}/builds", json={})
    assert r.status_code == 409
    assert r.json() == {"detail": "A build for acme_labs is already running"}


def test_start_returns_the_snapshot_and_passes_full(client, company, runner, gate):
    r = client.post(f"/api/companies/{company}/builds", json={"full": True})
    assert r.status_code == 202
    body = r.json()
    assert (body["slug"], body["kind"], body["state"]) == ("acme_labs", "build", "running")
    gate.set()
    wait_done(runner, company)
    assert runner.steps.calls == ["prepare", "fetch(None)", "ingest(full=True)"]


def test_start_without_body(client, company):
    assert client.post(f"/api/companies/{company}/builds").status_code == 202


def test_start_unknown_company_is_404(client, api_root):
    assert client.post("/api/companies/nope/builds", json={}).status_code == 404


def test_status_shows_building(client, company):
    client.post(f"/api/companies/{company}/builds", json={})
    assert client.get(f"/api/companies/{company}").json()["status"] == "building"
    listed = client.get("/api/companies").json()[0]
    assert listed["status"] == "building"
    assert listed["build"]["state"] == "running" and listed["build"]["stage"] == "prepare"
    assert listed["build"]["kind"] == "build"
    assert listed["build"]["stages"] == ["prepare", "fetch", "records", "normalize", "load"]
    assert (listed["build"]["step"], listed["build"]["steps"]) == (1, 5)


def test_failed_build_shows_failed_with_the_error(api_root, company, tmp_path):
    runner = JobRunner(steps=FakeSteps(fail_on="ingest"), jobs_dir=tmp_path / "jobs")
    client = TestClient(create_app(runner))
    client.post(f"/api/companies/{company}/builds", json={})
    wait_done(runner, company)
    body = client.get(f"/api/companies/{company}").json()
    assert body["status"] == "failed" and body["error"] == "boom"
    assert body["build"]["state"] == "failed"


def test_finished_build_status_comes_from_the_graph(client, company, runner, gate):
    client.post(f"/api/companies/{company}/builds", json={})
    gate.set()
    wait_done(runner, company)
    body = client.get(f"/api/companies/{company}").json()
    assert body["status"] == "empty"  # the patched graph check: done builds defer to the graph
    assert body["build"]["state"] == "done"


def test_current_is_404_before_any_build(client, company):
    r = client.get(f"/api/companies/{company}/builds/current")
    assert r.status_code == 404 and r.json() == {"detail": "No build for acme_labs yet"}


def test_current_returns_the_snapshot(client, company, runner, gate):
    client.post(f"/api/companies/{company}/builds", json={})
    gate.set()
    wait_done(runner, company)
    body = client.get(f"/api/companies/{company}/builds/current").json()
    assert body["state"] == "done" and body["events"][-1]["stage"] == "done"


def test_stop(client, company, runner, gate):
    client.post(f"/api/companies/{company}/builds", json={})
    r = client.delete(f"/api/companies/{company}/builds/current")
    assert r.status_code == 202
    gate.set()
    assert wait_done(runner, company).state == "stopped"


def test_stop_without_a_running_build_is_404(client, company, runner, gate):
    assert client.delete(f"/api/companies/{company}/builds/current").status_code == 404
    client.post(f"/api/companies/{company}/builds", json={})
    gate.set()
    wait_done(runner, company)
    assert client.delete(f"/api/companies/{company}/builds/current").status_code == 404


def test_startup_marks_a_build_cut_off_by_a_restart_as_stopped(api_root, company, tmp_path):
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    snap = BuildSnapshot(slug=company, kind="build", state="running", started_at="2026-10-16")
    (jobs / f"{company}.json").write_text(snap.model_dump_json())
    runner = JobRunner(steps=FakeSteps(), jobs_dir=jobs)
    with TestClient(create_app(runner)) as client:
        assert client.get(f"/api/companies/{company}/builds/current").json()["state"] == "stopped"


# --- per-company progress stream -------------------------------------------------------------


def test_events_stream_starts_with_snapshot(client, company, gate):
    client.post(f"/api/companies/{company}/builds", json={})
    gate.set()  # let the build finish, so the stream ends by itself
    with client.stream("GET", f"/api/companies/{company}/builds/current/events") as s:
        first = next(line for line in s.iter_lines() if line.startswith("event:"))
    assert first == "event: snapshot"


@pytest.mark.anyio
async def test_events_stream_sends_build_events_until_done(company, runner, gate):
    runner.start(company)  # held at the gate inside prepare
    stream = builds.progress_events(runner, company)
    first = await asyncio.wait_for(anext(stream), 2)
    snap = json.loads(first["data"])
    assert first["event"] == "snapshot" and snap["state"] == "running"
    gate.set()
    rest = [message async for message in stream]  # ends by itself on the build's last event
    assert rest and all(message["event"] == "build" for message in rest)
    sent = [(e["stage"], e["status"], e["at"]) for e in snap["events"]]
    sent += [(e["stage"], e["status"], e["at"]) for e in map(json.loads, (m["data"] for m in rest))]
    assert len(sent) == len(set(sent))  # nothing sent twice
    assert sent[-1][:2] == ("done", "done")
    steps = [json.loads(m["data"])["step"] for m in rest]  # each live event carries its step
    assert steps == sorted(steps) and steps[-1] == snap["steps"] == 5
    assert not runner._subscribers


def test_events_stream_of_a_finished_build_is_just_the_snapshot(client, company, runner, gate):
    client.post(f"/api/companies/{company}/builds", json={})
    gate.set()
    wait_done(runner, company)
    with client.stream("GET", f"/api/companies/{company}/builds/current/events") as s:
        events = sse(s.iter_lines())
    assert [name for name, _ in events] == ["snapshot"]
    assert events[0][1]["state"] == "done"


def test_events_stream_before_any_build_is_404(client, company):
    assert client.get(f"/api/companies/{company}/builds/current/events").status_code == 404


# --- global status stream --------------------------------------------------------------------


async def statuses_until_idle(runner: JobRunner, gate) -> list[dict]:
    """Drive the /api/events generator: one status per event until the build ends."""
    stream = builds.status_events(runner)
    pending = asyncio.ensure_future(anext(stream))
    while not runner._subscribers:  # the generator subscribes on its first step
        await asyncio.sleep(0)
    out: list[dict] = []
    try:
        runner.start("acme_labs")  # held at the gate inside prepare
        while not out or out[-1]["build"]["state"] not in TERMINAL:
            message = await asyncio.wait_for(pending, 2)
            assert message["event"] == "status"
            out.append(json.loads(message["data"]))
            gate.set()  # after the first status, which is then surely `building`
            pending = asyncio.ensure_future(anext(stream))
    finally:
        pending.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pending
        await stream.aclose()
    return out


@pytest.mark.anyio
async def test_status_stream_reports_building_then_the_end(company, runner, gate):
    out = await statuses_until_idle(runner, gate)
    assert {s["slug"] for s in out} == {company}
    assert out[0]["status"] == "building" and out[0]["build"]["state"] == "running"
    assert out[-1]["status"] == "empty" and out[-1]["build"]["state"] == "done"
    assert not runner._subscribers


@pytest.mark.anyio
async def test_status_message_is_the_company_as_the_list_shows_it(client, company, runner, gate):
    out = await statuses_until_idle(runner, gate)
    listed = client.get("/api/companies").json()[0]
    assert out[-1] == listed  # CompanyOut: the same fields and values as GET /api/companies
    assert "config" not in out[-1] and out[-1]["name"] == "Acme Labs"
    assert out[0]["build"]["kind"] == "build"
    assert out[0]["build"]["stages"] == ["prepare", "fetch", "records", "normalize", "load"]


@pytest.mark.anyio
async def test_status_stream_reports_a_broken_yaml_as_invalid(company, runner, gate):
    (config.companies_dir() / f"{company}.yaml").write_text("slug: [\n")
    out = await statuses_until_idle(runner, gate)
    assert {s["status"] for s in out} == {"invalid"} and out[-1]["error"]
    assert out[-1]["build"]["state"] == "done"


@pytest.mark.anyio
async def test_status_stream_survives_the_graph_going_down(company, runner, gate, monkeypatch):
    def down(slug):
        raise RedisConnectionError("down")

    monkeypatch.setattr("backend.api.companies.status_of", down)
    out = await statuses_until_idle(runner, gate)
    assert out[0]["status"] == "building" and out[0]["graph_reachable"] is False
    assert out[-1]["status"] == "unknown" and out[-1]["build"]["state"] == "done"


# --- Settings save (PUT) ---------------------------------------------------------------------


def test_dry_run_reports_rebuild(client, company):
    new = {**current_config(client, company), "window": {"since": "2026-06-01"}}
    before = yaml_text(company)
    d = client.put(f"/api/companies/{company}?dry_run=1", json=new).json()
    assert d["slug"] == company and d["rebuild"] is True and d["refetch"] == []
    assert yaml_text(company) == before


def test_put_needing_rebuild_without_flag_is_409(client, company):
    cfg = current_config(client, company)
    before = yaml_text(company)
    r = client.put(f"/api/companies/{company}", json=with_since(cfg, "2026-06-01"))
    assert r.status_code == 409 and r.json()["detail"]["rebuild_required"]["rebuild"]
    assert r.json()["detail"]["rebuild_required"]["slug"] == company
    assert yaml_text(company) == before


def test_put_with_rebuild_starts_rebuild(client, company, runner, gate):
    cfg = current_config(client, company)
    r = client.put(f"/api/companies/{company}?rebuild=1", json=with_since(cfg, "2026-06-01"))
    assert r.status_code == 202 and r.json()["kind"] == "rebuild"
    assert str(config.load_company(company).window.since) == "2026-06-01"
    gate.set()
    wait_done(runner, company)
    assert runner.steps.calls == ["reset", "prepare", "ingest(full=True)"]  # nothing to fetch


def test_put_without_changes_writes_nothing(client, company, runner):
    cfg = current_config(client, company)
    path = config.companies_dir() / f"{company}.yaml"
    path.write_text("# kept\n" + path.read_text())
    before = path.read_text()
    r = client.put(f"/api/companies/{company}", json=cfg)
    assert r.status_code == 200 and r.json()["config"] == cfg
    assert path.read_text() == before and runner.current(company) is None


def test_put_rename_saves_without_a_build(client, company, runner):
    cfg = current_config(client, company)
    r = client.put(f"/api/companies/{company}", json={**cfg, "name": "Acme"})
    assert r.status_code == 200 and r.json()["name"] == "Acme"
    assert config.load_company(company).name == "Acme"
    assert runner.current(company) is None


def test_put_adding_a_source_saves_and_fetches_only_it(client, company, runner, gate):
    cfg = current_config(client, company)
    added = {"type": "canonical_jsonl", "path": "data/inbox/acme_labs"}
    r = client.put(f"/api/companies/{company}", json={**cfg, "sources": [*cfg["sources"], added]})
    assert r.status_code == 200 and r.json()["status"] == "building"
    assert len(config.load_company(company).sources) == 2
    gate.set()
    snap = wait_done(runner, company)
    assert snap.kind == "build"
    assert runner.steps.calls[1] == "fetch(['canonical_jsonl:data/inbox/acme_labs'])"


def test_put_while_a_build_runs_is_409_and_writes_nothing(client, company):
    cfg = current_config(client, company)
    client.post(f"/api/companies/{company}/builds", json={})
    before = yaml_text(company)
    for query in ("", "?rebuild=1"):
        r = client.put(f"/api/companies/{company}{query}", json={**cfg, "name": "Acme"})
        assert r.status_code == 409
        assert r.json() == {"detail": "A build for acme_labs is already running"}
    assert yaml_text(company) == before


def test_dry_run_while_a_build_runs_still_answers(client, company):
    cfg = current_config(client, company)
    client.post(f"/api/companies/{company}/builds", json={})
    r = client.put(f"/api/companies/{company}?dry_run=1", json={**cfg, "name": "Acme"})
    assert r.status_code == 200 and r.json()["rebuild"] is False


def test_put_slug_mismatch_is_422(client, company):
    cfg = current_config(client, company)
    r = client.put(f"/api/companies/{company}", json={**cfg, "slug": "other"})
    assert r.status_code == 422 and r.json()["detail"][0]["loc"] == ["slug"]


def test_put_invalid_config_is_422_with_field_errors(client, company):
    cfg = current_config(client, company)
    r = client.put(f"/api/companies/{company}", json={**cfg, "sources": [{"type": "github"}]})
    assert r.status_code == 422 and r.json()["detail"][0]["loc"][:2] == ["sources", 0]


def test_put_unknown_company_is_404(client, company):
    cfg = current_config(client, company)
    assert client.put("/api/companies/nope", json={**cfg, "slug": "nope"}).status_code == 404


def test_put_decides_on_the_file_read_under_the_start_lock(client, company, monkeypatch):
    """Two saves at once: the second must compare against what the first wrote, so the file is
    read and diffed while the lock is held (dry runs and no-op saves may answer without it)."""
    held: list[bool] = []
    real = config_diff.diff

    def spy(old, new):
        held.append(client.app.state.start_lock.locked())
        return real(old, new)

    monkeypatch.setattr(config_diff, "diff", spy)
    cfg = current_config(client, company)
    assert client.put(f"/api/companies/{company}", json={**cfg, "name": "Acme"}).status_code == 200
    assert held[-1] is True
