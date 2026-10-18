"""Archive route: the Archivist's requests with their finds, and its runs in the activity."""

from __future__ import annotations

import pytest
from agents.keeper.model import ArchiveFind
from agents.testing import FakeClient

from .conftest import write
from .test_ask import make_client

ARCH = "citadel_archivist"


@pytest.fixture
def company(api_root):
    write(api_root, "synthetic", name="Synthetic Co")
    return "synthetic"


def open_request(ledger, uid, now, text="why drop sqlite", **kw):
    params = {"uid": uid, "kind": "topic", "text": text, "refs": [], "asked_by": "ask",
              "norm": text, "now": now, **kw}  # fmt: skip
    ledger.write("ledger/archive_open_request", ARCH, params)


def find(request, uid="github:a/b:issue:1"):
    return ArchiveFind(request=request, uid=uid, title="Drop sqlite", why="w", quote="q" * 20,
                       verdict="holds", date="2021-03-01",
                       evidence=["system:db"]).model_dump()  # fmt: skip


def test_requests_come_newest_first_with_their_finds(company, runner, ledger):
    open_request(ledger, "archive:old", "2026-10-17T09:00:00Z", text="old topic")
    open_request(ledger, "archive:new", "2026-10-17T10:00:00Z")
    ledger.write("ledger/archive_write_find", ARCH, find("archive:new"))
    client = make_client(runner, FakeClient())

    got = client.get(f"/api/companies/{company}/archive/requests").json()
    assert [r["uid"] for r in got["requests"]] == ["archive:new", "archive:old"]
    new, old = got["requests"]
    assert (new["kind"], new["status"], new["asked_by"], new["text"]) == (
        "topic", "open", "ask", "why drop sqlite")  # fmt: skip
    assert [(f["uid"], f["verdict"], f["date"], f["evidence"]) for f in new["finds"]] == [
        ("github:a/b:issue:1", "holds", "2021-03-01", ["system:db"])]  # fmt: skip
    assert old["finds"] == []
    one = client.get(f"/api/companies/{company}/archive/requests", params={"limit": 1}).json()
    assert [r["uid"] for r in one["requests"]] == ["archive:new"]


def test_no_requests_and_unknown_company(company, runner):
    client = make_client(runner, FakeClient())
    assert client.get(f"/api/companies/{company}/archive/requests").json() == {"requests": []}
    assert client.get("/api/companies/nope/archive/requests").status_code == 404
    bad = client.get(f"/api/companies/{company}/archive/requests", params={"limit": 0})
    assert bad.status_code == 422


def test_archive_runs_join_the_activity_newest_first(company, runner, ledger):
    open_request(ledger, "archive:a", "2026-10-17T09:00:00Z")
    ledger.write("ledger/write_step", ARCH, {"review": "archive:a", "n": 1, "actor": "archivist",
                 "tool": "archive_search", "input": {"q": "sqlite"}, "status": "done", "count": 2,
                 "touched": ["system:db"], "at": "2026-10-17T09:00:01Z"})  # fmt: skip
    open_request(ledger, "archive:quiet", "2026-10-17T09:30:00Z", text="no steps")  # left out
    client = make_client(runner, FakeClient())

    got = client.get(f"/api/companies/{company}/activity").json()
    [run] = got["runs"]
    assert (run["id"], run["source"], run["actor"], run["status"]) == (
        "archive:archive:a", "archive", "archivist", "stopped")  # fmt: skip
    assert [(s["actor"], s["tool"], s["touched"]) for s in run["steps"]] == [
        ("archivist", "archive_search", ["system:db"])]  # fmt: skip
    assert got["running"] is False


def test_startup_fails_ask_requests_a_restart_cut_off_and_wires_building(
    company, runner, ledger, monkeypatch
):
    from agents.archivist import live
    from backend.api import create_app
    from fastapi.testclient import TestClient

    open_request(ledger, "archive:cut", "2026-10-17T09:00:00Z")
    open_request(ledger, "archive:keeper", "2026-10-17T09:10:00Z", text="k", asked_by="keeper")
    monkeypatch.setattr(live, "_building", live._never)
    monkeypatch.setattr(runner, "building", lambda slug: slug == company)
    with TestClient(create_app(runner)):
        assert live.building(company) is True and live.building("other") is False
    got = {r["uid"]: r for r in ledger.read("ledger/archive_requests",
           {"statuses": ["open", "failed"], "limit": 10})}  # fmt: skip
    assert (got["archive:cut"]["status"], got["archive:cut"]["reason"]) == ("failed", "restart")
    assert got["archive:keeper"]["status"] == "open"  # the Keeper's are left to its reviews
