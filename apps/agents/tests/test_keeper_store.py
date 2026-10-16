"""The Keeper's ledger store (keeper_<slug>): the named ledger reads and writes.

Every case runs on `MemoryKeeperStore` and, when FalkorDB is up, on `KeeperStore` against a
throwaway keeper_test_<hex> graph that is deleted afterwards. FalkorDB-only checks are in
test_keeper_store_graph.py.
"""

from __future__ import annotations

import uuid

import pytest
from agents import acl
from agents.keeper.model import gap_uid, review_uid
from agents.keeper.store import READS, WRITES, KeeperStore, MemoryKeeperStore, delete_keeper_graph
from brain.testing import needs_graph

KEEPER = "citadel_keeper"
T1, T2, T3 = "2026-10-17T10:00:00Z", "2026-10-17T10:05:00Z", "2026-10-17T10:10:00Z"


@pytest.fixture(params=["memory", pytest.param("graph", marks=needs_graph)])
def store(request):
    slug = f"test_{uuid.uuid4().hex[:8]}"
    if request.param == "memory":
        yield MemoryKeeperStore(slug)
        return
    yield KeeperStore(slug)
    delete_keeper_graph(slug)


def open_gap(
    store, norm, trace_id=None, *, now=T1, kind="failed_question", subject=None, user=KEEPER
):
    return store.write(
        "ledger/open_gap",
        user,
        {
            "uid": gap_uid(),
            "kind": kind,
            "text": f"{norm}?",
            "norm": norm,
            "subject": subject,
            "about": [],
            "trace_id": trace_id,
            "now": now,
        },
    )


def get_gap(store, uid):
    [gap] = store.read("ledger/get_gap", {"uid": uid})
    return gap


def set_status(store, uid, frm, to, *, now=T2, reason=None, attempts_inc=0):
    params = {"uid": uid, "from": frm, "to": to, "reason": reason, "now": now}
    return store.write("ledger/set_gap_status", KEEPER, {**params, "attempts_inc": attempts_inc})


def test_names_are_listed():
    assert all(n.startswith("ledger/") for n in READS)
    assert {"ledger/open_gap", "work/write_episode", "memory/write_episode"} <= set(WRITES)


def test_open_gap_dedupes_on_norm(store):
    [first] = open_gap(store, "who owns billing", "t1", now=T1)
    [second] = open_gap(store, "who owns billing", "t2", now=T2)
    assert (first["created"], first["count"]) == (True, 1)
    assert (second["uid"], second["created"], second["count"]) == (first["uid"], False, 2)

    [gap] = store.read("ledger/gaps", {"statuses": ["open"], "limit": 10})
    assert (gap["uid"], gap["trace_ids"], gap["count"]) == (first["uid"], ["t1", "t2"], 2)
    assert (gap["status"], gap["attempts"], gap["created_at"], gap["updated_at"]) == (
        "open", 0, T1, T2)  # fmt: skip


def test_noticing_gap_dedupes_on_subject(store):
    [a] = open_gap(store, "billing owner left", kind="stale_owner", subject="system:billing")
    [b] = open_gap(store, "owner of billing is gone", kind="stale_owner", subject="system:billing")
    [c] = open_gap(store, "billing owner left", kind="stale_owner", subject="system:auth")
    assert b["uid"] == a["uid"] and b["count"] == 2
    assert c["created"] and c["uid"] != a["uid"]
    assert get_gap(store, a["uid"])["trace_ids"] == []  # noticing has no trace


def test_resolved_gap_is_not_bumped(store):
    [first] = open_gap(store, "who owns billing", "t1")
    assert set_status(store, first["uid"], ["open"], "resolved") == [
        {"uid": first["uid"], "status": "resolved"}]  # fmt: skip
    [again] = open_gap(store, "who owns billing", "t2", now=T3)
    assert again["created"] and again["uid"] != first["uid"]
    assert get_gap(store, first["uid"])["count"] == 1


def test_set_gap_status_guard(store):
    [g] = open_gap(store, "who owns billing", "t1")
    set_status(store, g["uid"], ["open"], "in_review")
    assert set_status(store, g["uid"], ["open"], "resolved") == []
    assert get_gap(store, g["uid"])["status"] == "in_review"

    out = set_status(store, g["uid"], ["in_review"], "open", reason="rejected", attempts_inc=1)
    assert out == [{"uid": g["uid"], "status": "open"}]
    gap = get_gap(store, g["uid"])
    assert (gap["attempts"], gap["reason"], gap["updated_at"]) == (1, "rejected", T2)
    assert store.read("ledger/get_gap", {"uid": "gap:nope"}) == []


def test_gaps_newest_first_by_status(store):
    [a] = open_gap(store, "a", now=T1)
    [b] = open_gap(store, "b", now=T2)
    [c] = open_gap(store, "c", now=T3)
    set_status(store, c["uid"], ["open"], "dismissed", now=T3)
    rows = store.read("ledger/gaps", {"statuses": ["open"], "limit": 10})
    assert [r["uid"] for r in rows] == [b["uid"], a["uid"]]
    both = store.read("ledger/gaps", {"statuses": ["open", "dismissed"], "limit": 2})
    assert [r["uid"] for r in both] == [c["uid"], b["uid"]]


def test_one_running_review(store):
    first, second, third = review_uid(), review_uid(), review_uid()
    start = {"trigger": "manual", "budget": 5, "now": T1}
    assert store.write("ledger/review_start", KEEPER, {"uid": first, **start}) == [{"uid": first}]
    assert store.write("ledger/review_start", KEEPER, {"uid": second, **start}) == []
    [current] = store.read("ledger/review_current", {})
    assert (current["uid"], current["state"], current["slug"], current["budget"]) == (
        first, "running", store.slug, 5)  # fmt: skip

    done = {"uid": first, "state": "done", "stop": None, "now": T2}
    assert store.write("ledger/review_finish", KEEPER, done) == [{"uid": first, "state": "done"}]
    assert store.write("ledger/review_finish", KEEPER, done) == []  # only a running one ends
    assert store.write("ledger/review_start", KEEPER, {"uid": third, **start}) == [{"uid": third}]
    [current] = store.read("ledger/review_current", {})
    assert current["uid"] == third  # the latest, though both started at T1

    assert store.write("ledger/review_stop_running", KEEPER, {"now": T3}) == [{"uid": third}]
    [current] = store.read("ledger/review_current", {})
    assert (current["state"], current["ended_at"], current["stop"]) == ("stopped", T3, "restart")


def test_review_current_empty(store):
    assert store.read("ledger/review_current", {}) == []


def test_log_and_read_log(store):
    for i, (gap, claim) in enumerate([("gap:1", None), ("gap:2", "claim:1"), ("gap:1", None)]):
        entry = {"uid": f"log:{i}", "at": T1, "actor": "keeper", "action": "gap_opened"}
        row = {**entry, "why": f"step {i}", "gap": gap, "claim": claim, "evidence": ["pr:1"]}
        assert store.write("ledger/log", KEEPER, row) == [{"uid": f"log:{i}"}]
    rows = store.read("ledger/read_log", {"limit": 10})
    assert [r["uid"] for r in rows] == ["log:2", "log:1", "log:0"]  # newest first, same `at`
    assert rows[1] == {
        "uid": "log:1", "at": T1, "actor": "keeper", "action": "gap_opened", "why": "step 1",
        "gap": "gap:2", "claim": "claim:1", "evidence": ["pr:1"]}  # fmt: skip
    assert [r["uid"] for r in store.read("ledger/read_log", {"limit": 10, "gap": "gap:1"})] == [
        "log:2", "log:0"]  # fmt: skip
    assert [r["uid"] for r in store.read("ledger/read_log", {"limit": 1, "claim": "claim:1"})] == [
        "log:1"]  # fmt: skip


@pytest.mark.parametrize("name", ["work/write_episode", "memory/write_episode"])
def test_episode_becomes_log_entry(store, name):
    params = {
        "agent": "agent:keeper",
        "now": 1_792_224_000,  # runner passes Ctx.now, an epoch int
        "run_at": 1_792_224_000,
        "tick": 0,
        "input": "keeper.decide gap:1",
        "summary": "Claimed the owner of Billing.",
        "tools_called": ["experts_for_system"],
        "actions": ["claim:1"],
        "stop": None,
    }
    [row] = store.write(name, "citadel_pm", params)
    [entry] = store.read("ledger/read_log", {"limit": 10})
    assert entry["uid"] == row["episode"]
    assert (entry["action"], entry["actor"], entry["why"], entry["evidence"]) == (
        "episode", "agent:keeper", "Claimed the owner of Billing.", ["claim:1"])  # fmt: skip
    assert entry["at"] == "2026-10-17T08:00:00Z"


def test_acl_refused(store):
    with pytest.raises(acl.Refused):
        open_gap(store, "who owns billing", "t1", user="citadel_risk")
    with pytest.raises(acl.Refused):
        store.read("ledger/gaps", {"statuses": ["open"], "limit": 1}, db_user="citadel_risk")
    assert open_gap(store, "who owns billing", "t1", user="citadel_brain")[0]["created"]
    assert store.read("ledger/gaps", {"statuses": ["open"], "limit": 1}, db_user="citadel_qa")


def test_unknown_names(store):
    with pytest.raises(KeyError):
        store.read("ledger/nope", {})
    with pytest.raises(KeyError):
        store.write("ledger/nope", KEEPER, {})
    with pytest.raises(KeyError):
        store.read("ledger/open_gap", {})  # a write is not a read
