"""The Archivist's ledger records (requests, finds) on both ledger stores.

Every case runs on `MemoryKeeperStore` and, when FalkorDB is up, on `KeeperStore` against a
throwaway keeper_test_<hex> graph that is deleted afterwards.
"""

from __future__ import annotations

import uuid

import pytest
from agents import acl
from agents.keeper.model import ArchiveFind, archive_uid, gap_uid
from agents.keeper.store import READS, WRITES, KeeperStore, MemoryKeeperStore, delete_keeper_graph
from brain.testing import needs_graph

ARCH = "citadel_archivist"
T1, T2, T3 = "2026-10-17T10:00:00Z", "2026-10-17T10:05:00Z", "2026-10-17T10:10:00Z"


@pytest.fixture(params=["memory", pytest.param("graph", marks=needs_graph)])
def store(request):
    slug = f"test_{uuid.uuid4().hex[:8]}"
    if request.param == "memory":
        yield MemoryKeeperStore(slug)
        return
    yield KeeperStore(slug)
    delete_keeper_graph(slug)


def open_request(store, norm="drop sqlite", *, uid=None, now=T1, user=ARCH, **kw):
    params = {
        "uid": uid or archive_uid(), "kind": "topic", "text": "why drop sqlite", "refs": [],
        "asked_by": "ask", "norm": norm, "now": now, **kw,
    }  # fmt: skip
    return store.write("ledger/archive_open_request", user, params)


def get(store, uid):
    [row] = store.read("ledger/archive_get_request", {"uid": uid})
    return row


def move(store, uid, frm, to, *, now=T2, **kw):
    params = {"uid": uid, "from": frm, "to": to, "now": now, **kw}
    return store.write("ledger/archive_set_request", ARCH, params)


def test_new_names_are_known():
    for name in ("get_request", "queue", "finds", "recall", "requests", "requests_for_gap"):
        assert f"ledger/archive_{name}" in READS
    for name in ("open_request", "set_request", "write_find"):
        assert f"ledger/archive_{name}" in WRITES


def test_archivist_acl():
    g = "keeper_acme"
    assert acl.can(ARCH, "acme", g, "W") and acl.can(ARCH, "acme", "brain_acme", "R")
    assert not acl.can(ARCH, "acme", "brain_acme", "W")
    assert not acl.can(ARCH, "acme", "agent_acme", "R")


def test_open_request_defaults(store):
    uid = archive_uid()
    [row] = open_request(store, uid=uid, refs=["a#1"], from_uid="system:db", thread="t1")
    assert row == {"uid": uid, "created": True, "status": "open"}
    r = get(store, uid)
    assert (r["kind"], r["refs"], r["status"], r["outcome"]) == ("topic", ["a#1"], "open", None)
    assert (r["from_uid"], r["gap"], r["thread"]) == ("system:db", None, "t1")
    assert (r["partial"], r["calls"], r["created_at"], r["updated_at"]) == (False, 0, T1, T1)


def test_open_request_dedupes_on_norm(store):
    [first] = open_request(store)
    [again] = open_request(store, now=T2)
    assert again == {"uid": first["uid"], "created": False, "status": "open"}
    move(store, first["uid"], ["open"], "running")
    [while_running] = open_request(store, now=T3)
    assert while_running["uid"] == first["uid"] and while_running["status"] == "running"
    [other] = open_request(store, norm="something else")
    assert other["created"] is True
    move(store, first["uid"], ["running"], "answered", outcome="found")
    [fresh] = open_request(store, now=T3)
    assert fresh["created"] is True and fresh["uid"] != first["uid"]


def test_open_request_refuses_a_bad_kind_and_the_wrong_user(store):
    with pytest.raises(ValueError):
        open_request(store, kind="nonsense")
    with pytest.raises(acl.Refused):
        open_request(store, user="citadel_loader")


def test_set_request_is_guarded(store):
    [row] = open_request(store)
    uid = row["uid"]
    assert move(store, uid, ["running"], "answered") == []  # still open
    assert move(store, uid, ["open"], "running") == [{"uid": uid, "status": "running"}]
    assert move(store, uid, ["open"], "running") == []  # a second claim of it loses
    done = move(store, uid, ["running"], "answered", outcome="nothing_found", summary="none",
                partial=True, calls=4, now=T3)  # fmt: skip
    assert done == [{"uid": uid, "status": "answered"}]
    r = get(store, uid)
    assert (r["outcome"], r["summary"], r["partial"], r["calls"], r["updated_at"]) == (
        "nothing_found", "none", True, 4, T3,
    )  # fmt: skip
    assert move(store, "archive:missing", ["open"], "running") == []
    with pytest.raises(ValueError):
        move(store, uid, ["answered"], "bogus")
    with pytest.raises(ValueError):
        move(store, uid, ["answered"], "answered", outcome="bogus")


def test_failed_request_keeps_its_reason(store):
    [row] = open_request(store)
    move(store, row["uid"], ["open"], "failed", reason="rate limited")
    assert get(store, row["uid"])["reason"] == "rate limited"


def test_queue_is_open_requests_oldest_first(store):
    a = open_request(store, "a", now=T2)[0]["uid"]
    b = open_request(store, "b", now=T1)[0]["uid"]
    c = open_request(store, "c", now=T3)[0]["uid"]
    move(store, c, ["open"], "running")
    assert [r["uid"] for r in store.read("ledger/archive_queue", {"limit": 10})] == [b, a]
    assert [r["uid"] for r in store.read("ledger/archive_queue", {"limit": 1})] == [b]


def _find(request, uid="github:a/b:issue:1", **kw) -> dict:
    base = {
        "request": request, "uid": uid, "title": "T", "why": "w", "quote": "q" * 20,
        "verdict": "holds", "evidence": ["system:db"],
    }  # fmt: skip
    return ArchiveFind(**{**base, **kw}).model_dump()


def test_write_find_upserts_per_request_and_item(store):
    req = open_request(store)[0]["uid"]
    other = open_request(store, "other")[0]["uid"]
    [row] = store.write("ledger/archive_write_find", ARCH, _find(req))
    assert row == {"request": req, "uid": "github:a/b:issue:1"}
    store.write("ledger/archive_write_find", ARCH, _find(req, why="better", date="2023-04-01"))
    second = _find(req, uid="github:a/b:issue:2", url="https://x/2", verdict="superseded")
    second["superseded_by"] = "github:a/b:issue:9"
    store.write("ledger/archive_write_find", ARCH, second)
    store.write("ledger/archive_write_find", ARCH, _find(other))
    finds = store.read("ledger/archive_finds", {"requests": [req]})
    assert [f["uid"] for f in finds] == ["github:a/b:issue:1", "github:a/b:issue:2"]
    assert (finds[0]["why"], finds[0]["date"], finds[0]["url"]) == ("better", "2023-04-01", None)
    assert (finds[1]["verdict"], finds[1]["superseded_by"]) == ("superseded", "github:a/b:issue:9")
    assert finds[0]["evidence"] == ["system:db"]
    assert len(store.read("ledger/archive_finds", {"requests": [req, other]})) == 3


def test_write_find_needs_its_request_and_a_valid_verdict(store):
    assert store.write("ledger/archive_write_find", ARCH, _find("archive:missing")) == []
    req = open_request(store)[0]["uid"]
    with pytest.raises(ValueError):
        store.write("ledger/archive_write_find", ARCH, {**_find(req), "verdict": "maybe"})
    assert store.read("ledger/archive_finds", {"requests": [req]}) == []


def test_recall_read(store):
    uid = open_request(store)[0]["uid"]
    params = {"norm": "drop sqlite", "asked_by": "ask", "since": T1}
    assert store.read("ledger/archive_recall", params) == []  # not answered yet
    move(store, uid, ["open"], "answered", outcome="nothing_found", now=T2)
    assert [r["uid"] for r in store.read("ledger/archive_recall", params)] == [uid]
    assert store.read("ledger/archive_recall", {**params, "asked_by": "keeper"}) == []
    assert store.read("ledger/archive_recall", {**params, "since": T3}) == []
    newer = open_request(store, now=T3)[0]["uid"]
    move(store, newer, ["open"], "answered", outcome="found", partial=True, now=T3)
    assert [r["uid"] for r in store.read("ledger/archive_recall", params)] == [uid]


def test_requests_listing_and_for_gap(store):
    gap = gap_uid()
    a = open_request(store, "a", now=T1, gap=gap)[0]["uid"]
    b = open_request(store, "b", now=T2, gap=gap)[0]["uid"]
    c = open_request(store, "c", now=T3)[0]["uid"]
    move(store, a, ["open"], "failed", now=T3)
    listed = store.read("ledger/archive_requests", {"statuses": ["open", "failed"], "limit": 10})
    assert [r["uid"] for r in listed] == sorted([a, c], reverse=True) + [b]  # T3, T3, T2
    assert len(store.read("ledger/archive_requests", {"statuses": ["open"], "limit": 1})) == 1
    for_gap = store.read("ledger/archive_requests_for_gap", {"gap": gap})
    assert [r["uid"] for r in for_gap] == [a, b]  # a was updated last (T3)


def test_waiting_archive_gap_absorbs_a_repeat(store):
    def open_gap(now, trace):
        return store.write("ledger/open_gap", "citadel_brain", {
            "uid": gap_uid(), "kind": "failed_question", "text": "why sqlite?",
            "norm": "why sqlite", "subject": None, "about": [], "trace_id": trace, "now": now,
        })  # fmt: skip

    [first] = open_gap(T1, "t1")
    store.write("ledger/set_gap_status", "citadel_keeper", {
        "uid": first["uid"], "from": ["open"], "to": "waiting_archive",
        "reason": "asked", "now": T2,
    })  # fmt: skip
    [second] = open_gap(T3, "t2")
    assert second["uid"] == first["uid"] and second["created"] is False and second["count"] == 2
    [gap] = store.read("ledger/get_gap", {"uid": first["uid"]})
    assert gap["status"] == "waiting_archive" and gap["archive_asked"] is False


def test_archive_conflict_gap_kind(store):
    [row] = store.write("ledger/open_gap", "citadel_keeper", {
        "uid": gap_uid(), "kind": "archive_conflict", "text": "old vs new owner",
        "norm": "old new owner", "now": T1,
    })  # fmt: skip
    assert row["created"] is True
