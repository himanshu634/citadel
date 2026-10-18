"""The Keeper's ledger store (keeper_<slug>): gaps, log, reviews, consults, claims and
follow-ups through the named ledger reads and writes.

Every case runs on `MemoryKeeperStore` and, when FalkorDB is up, on `KeeperStore` against a
throwaway keeper_test_<hex> graph that is deleted afterwards. FalkorDB-only checks are in
test_keeper_store_graph.py.
"""

from __future__ import annotations

import uuid

import pytest
from agents import acl
from agents.keeper.model import Claim, claim_uid, gap_uid, review_uid
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
    assert {"ledger/open_gap", "ledger/write_episode"} <= set(WRITES)


def test_the_same_trace_twice_is_one_sighting(store):
    [first] = open_gap(store, "who owns billing", "t1", now=T1)
    [again] = open_gap(store, "who owns billing", "t1", now=T2)
    assert (again["uid"], again["created"], again["count"]) == (first["uid"], False, 1)
    [gap] = store.read("ledger/gaps", {"statuses": ["open"], "limit": 10})
    assert (gap["trace_ids"], gap["count"], gap["updated_at"]) == (["t1"], 1, T1)
    [other] = open_gap(store, "who owns billing", "t2", now=T3)
    assert other["count"] == 2


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


def test_latest_gap_for_subject(store):
    def latest(kind, subject):
        q = {"kind": kind, "subject": subject}
        return [g["uid"] for g in store.read("ledger/latest_gap_for_subject", q)]

    [a] = open_gap(store, "billing owner left", kind="stale_owner", subject="system:billing")
    open_gap(store, "auth owner left", kind="stale_owner", subject="system:auth", now=T2)
    open_gap(store, "billing is hot", kind="unowned_hot_system", subject="system:billing",
             now=T3)  # fmt: skip
    assert latest("stale_owner", "system:billing") == [a["uid"]]
    set_status(store, a["uid"], ["open"], "resolved")
    [b] = open_gap(store, "billing owner left again", kind="stale_owner",
                   subject="system:billing", now=T3)  # fmt: skip
    assert b["created"] and latest("stale_owner", "system:billing") == [b["uid"]]
    [g] = store.read("ledger/latest_gap_for_subject",
                     {"kind": "stale_owner", "subject": "system:billing"})  # fmt: skip
    assert (g["status"], g["subject"]) == ("open", "system:billing")
    assert latest("stale_owner", "system:nowhere") == []


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


def test_a_running_review_blocks_a_start_until_it_is_stopped(store):
    """Only the API runs reviews (`backend.keeper_runs`), so the ledger keeps no sign of life: a
    running review blocks a start however old it is, steps leave the review as it was, and
    `review_stop_running` stops every running review, however fresh."""
    live, other = review_uid(), review_uid()
    start = {"trigger": "manual", "budget": 5}
    assert store.write("ledger/review_start", KEEPER, {"uid": live, **start, "now": T1})
    step = {"review": live, "n": 1, "actor": "pm", "tool": "work_history", "at": T1}
    store.write("ledger/write_step", KEEPER, step)
    done = {"review": live, "n": 1, "status": "done", "count": 1, "at": T1}
    store.write("ledger/finish_step", KEEPER, done)
    [current] = store.read("ledger/review_current", {})
    assert "heartbeat_at" not in current
    later = {"uid": other, **start, "now": "2027-10-17T10:00:00Z"}  # a year on
    assert store.write("ledger/review_start", KEEPER, later) == []

    assert store.write("ledger/review_stop_running", KEEPER, {"now": T1}) == [{"uid": live}]
    [current] = store.read("ledger/review_current", {})
    assert (current["uid"], current["state"], current["stop"], current["ended_at"]) == (
        live, "stopped", "restart", T1)  # fmt: skip
    assert store.write("ledger/review_start", KEEPER, {"uid": other, **start, "now": T2}) == [
        {"uid": other}]  # fmt: skip
    assert store.write("ledger/review_stop_running", KEEPER, {"now": T2}) == [{"uid": other}]
    assert store.write("ledger/review_stop_running", KEEPER, {"now": T3}) == []  # none left


def test_an_archive_review_starts(store):
    uid = review_uid()
    start = {"uid": uid, "trigger": "archive", "budget": 2, "now": T1}
    assert store.write("ledger/review_start", KEEPER, start) == [{"uid": uid}]
    assert store.read("ledger/review_current", {})[0]["trigger"] == "archive"


def test_review_current_empty(store):
    assert store.read("ledger/review_current", {}) == []


def start_review(store, uid=None, *, now=T1):
    uid = uid or review_uid()
    store.write("ledger/review_start", KEEPER, {"uid": uid, "trigger": "build", "budget": 3,
                                                "now": now})  # fmt: skip
    return uid


def test_review_steps_round_trip(store):
    rid, other = start_review(store), None
    step = {"review": rid, "n": 1, "actor": "pm", "tool": "work_history",
            "input": '{"system": "Auth", "limit": 10}', "at": T1}  # fmt: skip
    assert store.write("ledger/write_step", KEEPER, step) == [{"review": rid, "n": 1}]
    [running] = store.read("ledger/review_steps", {"reviews": [rid]})
    assert running == {
        "review": rid, "n": 1, "actor": "pm", "tool": "work_history", "kind": "graph",
        "input": {"system": "Auth", "limit": 10}, "status": "running", "count": None,
        "error": None, "touched": [], "started_at": T1, "ended_at": None}  # fmt: skip

    done = {"review": rid, "n": 1, "status": "done", "count": 2, "touched": ["system:Auth", "pr:1"],
            "at": T2}  # fmt: skip
    assert store.write("ledger/finish_step", KEEPER, done) == [
        {"review": rid, "n": 1, "status": "done"}]  # fmt: skip
    assert store.write("ledger/finish_step", KEEPER, {**done, "status": "failed"}) == []  # once
    submit = {"review": rid, "n": 2, "actor": "pm", "tool": "submit_consult", "kind": "submit",
              "input": {"can_ground": True}, "status": "failed", "error": "write_refused",
              "at": T3}  # fmt: skip
    store.write("ledger/write_step", KEEPER, submit)  # a dict input is stored as JSON text
    first, second = store.read("ledger/review_steps", {"reviews": [rid]})
    assert (first["status"], first["count"], first["touched"], first["ended_at"]) == (
        "done", 2, ["system:Auth", "pr:1"], T2)  # fmt: skip
    assert (second["kind"], second["input"], second["status"], second["error"]) == (
        "submit", {"can_ground": True}, "failed", "write_refused")  # fmt: skip
    assert (second["started_at"], second["ended_at"]) == (T3, T3)  # written ended

    store.write("ledger/review_finish", KEEPER, {"uid": rid, "state": "done", "now": T3})
    other = start_review(store)
    assert store.read("ledger/review_steps", {"reviews": [other]}) == []
    store.write("ledger/write_step", KEEPER, {**step, "review": other, "tool": "impact_of"})
    both = store.read("ledger/review_steps", {"reviews": [other, rid]})  # one read, many reviews
    assert sorted((s["review"], s["n"], s["tool"]) for s in both) == sorted([
        (rid, 1, "work_history"), (rid, 2, "submit_consult"), (other, 1, "impact_of")])  # fmt: skip
    assert [s["n"] for s in both if s["review"] == rid] == [1, 2]  # in order within a review
    no_review = {**step, "review": "review:nope"}
    assert store.write("ledger/write_step", KEEPER, no_review) == []  # only on a known review
    with pytest.raises(ValueError):
        store.write("ledger/write_step", KEEPER, {**step, "n": 3, "status": "lost"})


@pytest.mark.parametrize("bad", ["not json", "[1, 2]", '"text"', 5])
def test_a_step_input_must_be_a_json_object(store, bad):
    rid = start_review(store)
    step = {"review": rid, "n": 1, "actor": "pm", "tool": "work_history", "input": bad, "at": T1}
    with pytest.raises(ValueError):
        store.write("ledger/write_step", KEEPER, step)
    assert store.read("ledger/review_steps", {"reviews": [rid]}) == []


def test_recent_reviews_newest_first_and_picked_gaps(store):
    first = start_review(store)
    store.write("ledger/review_finish", KEEPER, {"uid": first, "state": "done", "now": T2})
    second = start_review(store)  # the same `now`: start order decides
    picked = {"uid": second, "gaps": ["gap:a", "gap:b"], "gap_text": "Who owns Auth?"}
    assert store.write("ledger/review_picked", KEEPER, picked) == [{"uid": second}]
    rows = store.read("ledger/recent_reviews", {"limit": 5})
    assert [r["uid"] for r in rows] == [second, first]
    assert (rows[0]["gaps"], rows[0]["gap_text"]) == (["gap:a", "gap:b"], "Who owns Auth?")
    assert (rows[1]["gaps"], rows[1]["gap_text"], rows[1]["state"]) == ([], None, "done")
    assert [r["uid"] for r in store.read("ledger/recent_reviews", {"limit": 1})] == [second]
    store.write("ledger/review_finish", KEEPER, {"uid": second, "state": "skipped", "now": T2})
    skipped = start_review(store)
    store.write("ledger/review_finish", KEEPER, {"uid": skipped, "state": "skipped", "now": T2})
    third = start_review(store)  # running
    assert [r["uid"] for r in store.read("ledger/recent_reviews", {"limit": 5})] == [third, first]


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


def test_episode_becomes_log_entry(store):
    params = {
        "agent": "agent:keeper",
        "now": 1_792_224_000,  # runner passes Ctx.now, an epoch int
        "run_at": 1_792_224_000,
        "input": "keeper.decide gap:1",
        "summary": "Claimed the owner of Billing.",
        "tools_called": ["experts_for_system"],
        "actions": ["claim:1", "claim_written"],
        "stop": None,
    }
    [row] = store.write("ledger/write_episode", "citadel_pm", params)
    [entry] = store.read("ledger/read_log", {"limit": 10, "gap": "gap:1"})
    assert entry["uid"] == row["episode"]
    assert (entry["action"], entry["actor"], entry["why"], entry["evidence"]) == (
        "episode", "agent:keeper", "keeper.decide gap:1: Claimed the owner of Billing.",
        ["claim:1"])  # fmt: skip
    assert (entry["gap"], entry["claim"], entry["at"]) == ("gap:1", None, "2026-10-17T08:00:00Z")


def test_episode_of_a_claim_job(store):
    params = {"agent": "agent:pm", "now": T1, "input": "pm.follow_up claim:7", "summary": "Done."}
    store.write("ledger/write_episode", "citadel_pm", {**params, "actions": []})
    [entry] = store.read("ledger/read_log", {"limit": 10, "claim": "claim:7"})
    assert (entry["gap"], entry["claim"], entry["why"], entry["evidence"]) == (
        None, "claim:7", "pm.follow_up claim:7: Done.", [])  # fmt: skip


def test_acl_refused(store):
    with pytest.raises(acl.Refused):
        open_gap(store, "who owns billing", "t1", user="citadel_loader")
    with pytest.raises(acl.Refused):
        store.read("ledger/gaps", {"statuses": ["open"], "limit": 1}, db_user="citadel_loader")
    assert open_gap(store, "who owns billing", "t1", user="citadel_brain")[0]["created"]
    assert store.read("ledger/gaps", {"statuses": ["open"], "limit": 1}, db_user="citadel_qa")


def test_unknown_names(store):
    with pytest.raises(KeyError):
        store.read("ledger/nope", {})
    with pytest.raises(KeyError):
        store.write("ledger/nope", KEEPER, {})
    with pytest.raises(KeyError):
        store.read("ledger/open_gap", {})  # a write is not a read


# --- consults, claims and follow-ups -------------------------------------------------------


def write_claim(store, kind="owner", status="accepted", *, subject="system:billing", now=T1):
    claim = Claim(
        uid=claim_uid(),
        kind=kind,
        subject=subject,
        statement=f"{kind} of {subject}",
        value="person:alice",
        about=[subject],
        evidence=["pr:1", "pr:2"],
        status=status,
        author="keeper",
        why="Alice merged most Billing changes.",
        gap="gap:1",
        created_at=now,
        updated_at=now,
    )
    assert store.write("ledger/write_claim", KEEPER, claim.model_dump()) == [{"uid": claim.uid}]
    return claim


def test_consult_round_trip(store):
    [g] = open_gap(store, "who owns billing", "t1")
    gap, uid = g["uid"], f"consult:{g['uid']}:pm:0"
    post = {"gap": gap, "role": "pm", "attempt": 0, "now": T1}
    assert store.write("ledger/post_consult", KEEPER, post) == [{"uid": uid, "created": True}]
    assert store.write("ledger/post_consult", KEEPER, {**post, "now": T2}) == [
        {"uid": uid, "created": False}]  # fmt: skip
    store.write("ledger/post_consult", KEEPER, {**post, "role": "qa"})

    [queued] = store.read("ledger/queue_consult", {"role": "pm"})
    assert (queued["uid"], queued["gap"], queued["status"], queued["can_ground"]) == (
        uid, gap, "open", None)  # fmt: skip
    assert (queued["created_at"], queued["attempt"]) == (T1, 0)  # the second post changed nothing

    answer = {
        "consult": uid,
        "can_ground": True,
        "kind": "owner",
        "subject": "system:billing",
        "statement": "Alice owns Billing.",
        "value": "person:alice",
        "cites": ["pr:1"],
        "now": T2,
    }
    assert store.write("ledger/answer_consult", "citadel_pm", answer) == [
        {"uid": uid, "status": "answered"}]  # fmt: skip
    assert store.read("ledger/queue_consult", {"role": "pm"}) == []
    assert store.write("ledger/answer_consult", "citadel_pm", answer) == []  # answered once

    pm, qa = store.read("ledger/consults_for_gap", {"gap": gap})
    assert (pm["role"], pm["status"], pm["can_ground"], pm["cites"], pm["value"]) == (
        "pm", "answered", True, ["pr:1"], "person:alice")  # fmt: skip
    assert (qa["role"], qa["status"], qa["cites"]) == ("qa", "open", [])


def test_queue_consult_oldest_first(store):
    post = {"role": "qa", "attempt": 0}
    store.write("ledger/post_consult", KEEPER, {**post, "gap": "gap:2", "now": T2})
    store.write("ledger/post_consult", KEEPER, {**post, "gap": "gap:1", "now": T1})
    rows = store.read("ledger/queue_consult", {"role": "qa"})
    assert [r["uid"] for r in rows] == ["consult:gap:1:qa:0", "consult:gap:2:qa:0"]


def test_consults_per_attempt(store):
    """A gap reopened after a rejected claim (attempts + 1) gets fresh consults."""
    [g] = open_gap(store, "who owns billing", "t1")
    gap = g["uid"]
    store.write("ledger/post_consult", KEEPER, {"gap": gap, "role": "pm", "attempt": 0, "now": T1})
    answer = {"consult": f"consult:{gap}:pm:0", "can_ground": False, "now": T1}
    store.write("ledger/answer_consult", "citadel_pm", answer)
    set_status(store, gap, ["open"], "in_review")
    set_status(store, gap, ["in_review"], "open", reason="rejected", attempts_inc=1)

    assert store.read("ledger/consults_for_gap", {"gap": gap}) == []  # attempt 0 is history
    post = {"gap": gap, "role": "pm", "attempt": 1, "now": T2}
    assert store.write("ledger/post_consult", KEEPER, post) == [
        {"uid": f"consult:{gap}:pm:1", "created": True}]  # fmt: skip
    [c] = store.read("ledger/consults_for_gap", {"gap": gap})
    assert (c["uid"], c["attempt"], c["status"]) == (f"consult:{gap}:pm:1", 1, "open")
    assert [r["uid"] for r in store.read("ledger/queue_consult", {"role": "pm"})] == [c["uid"]]


def test_gap_archive_asked_once(store):
    """A gap asks the Archivist once, ever: the flag is set by a guarded write."""
    [g] = open_gap(store, "who decided the old auth system", "t1")
    assert get_gap(store, g["uid"])["archive_asked"] is False
    asked = {"uid": g["uid"]}
    assert store.write("ledger/gap_archive_asked", KEEPER, asked) == [{"uid": g["uid"]}]
    assert store.write("ledger/gap_archive_asked", KEEPER, asked) == []  # once
    assert store.write("ledger/gap_archive_asked", KEEPER, {"uid": "gap:none"}) == []
    assert get_gap(store, g["uid"])["archive_asked"] is True


def test_consults_after_the_archive_are_a_fresh_round(store):
    """Once a gap asked the Archivist, its consults are a new round of the same attempt (uid
    suffix :archive), so a gap the Archivist sends back is consulted again with no attempt used;
    the round before is history."""
    [g] = open_gap(store, "who decided the old auth system", "t1")
    gap = g["uid"]
    store.write("ledger/post_consult", KEEPER, {"gap": gap, "role": "pm", "attempt": 0, "now": T1})
    store.write("ledger/answer_consult", "citadel_pm",
                {"consult": f"consult:{gap}:pm:0", "can_ground": False, "now": T1})  # fmt: skip
    store.write("ledger/gap_archive_asked", KEEPER, {"uid": gap})

    assert store.read("ledger/consults_for_gap", {"gap": gap}) == []  # the round before
    post = {"gap": gap, "role": "pm", "attempt": 0, "archive": True, "now": T2}
    assert store.write("ledger/post_consult", KEEPER, post) == [
        {"uid": f"consult:{gap}:pm:0:archive", "created": True}]  # fmt: skip
    assert store.write("ledger/post_consult", KEEPER, post)[0]["created"] is False
    [c] = store.read("ledger/consults_for_gap", {"gap": gap})
    assert (c["uid"], c["attempt"], c["archive"], c["status"]) == (
        f"consult:{gap}:pm:0:archive", 0, True, "open")  # fmt: skip
    assert [r["uid"] for r in store.read("ledger/queue_consult", {"role": "pm"})] == [c["uid"]]


def test_review_finish_records_the_gaps_the_archive_reopened(store):
    rid = start_review(store)
    done = {"uid": rid, "state": "done", "archive_reopened": ["gap:1", "gap:2"], "now": T2}
    store.write("ledger/review_finish", KEEPER, done)
    [current] = store.read("ledger/review_current", {})
    assert current["archive_reopened"] == ["gap:1", "gap:2"]
    other = start_review(store, now=T3)
    store.write("ledger/review_finish", KEEPER, {"uid": other, "state": "done", "now": T3})
    assert store.read("ledger/review_current", {})[0]["archive_reopened"] == []


def test_write_and_read_claims(store):
    c = write_claim(store, status="pending_approval")
    assert store.write("ledger/write_claim", KEEPER, c.model_dump()) == []  # uid taken
    [got] = store.read("ledger/get_claim", {"uid": c.uid})
    assert got == c.model_dump()
    other = write_claim(store, "expert", subject="system:auth", now=T2)

    rows = store.read("ledger/claims", {"statuses": ["pending_approval", "accepted"], "limit": 5})
    assert [r["uid"] for r in rows] == [other.uid, c.uid]  # newest first
    one = {"kind": "owner", "subject": "system:billing", "statuses": ["pending_approval"]}
    assert [r["uid"] for r in store.read("ledger/claims_for_subject", one)] == [c.uid]
    assert store.read("ledger/claims_for_subject", {**one, "statuses": ["accepted"]}) == []
    assert store.read("ledger/get_claim", {"uid": "claim:nope"}) == []


def test_claim_status_guard(store):
    c = write_claim(store, status="pending_approval")
    move = {"uid": c.uid, "from": ["pending_approval"], "to": "accepted", "now": T2}
    approve = {**move, "by": "Dana", "why": "Checked with Alice."}
    assert store.write("ledger/set_claim_status", KEEPER, approve) == [
        {"uid": c.uid, "status": "accepted"}]  # fmt: skip
    assert store.write("ledger/set_claim_status", KEEPER, {**approve, "by": "Eve"}) == []
    [got] = store.read("ledger/get_claim", {"uid": c.uid})
    assert (got["status"], got["approved_by"], got["why"], got["updated_at"]) == (
        "accepted", "Dana", "Checked with Alice.", T2)  # fmt: skip
    assert got["valid_from"] == T2 and got["valid_to"] is None

    supersede = {"uid": c.uid, "from": ["accepted"], "to": "superseded", "now": T3}
    out = store.write(
        "ledger/set_claim_status", KEEPER, {**supersede, "by": "auto", "why": None, "valid_to": T3}
    )
    assert out == [{"uid": c.uid, "status": "superseded"}]
    [got] = store.read("ledger/get_claim", {"uid": c.uid})
    assert (got["valid_to"], got["approved_by"], got["why"]) == (T3, "Dana", "Checked with Alice.")


def test_claims_for_gap(store):
    """The decide queue skips a gap whose claim waits for a lead."""
    pending = write_claim(store, status="pending_approval", now=T1)
    rejected = write_claim(store, "expert", "rejected", now=T2)
    other = write_claim(store, status="pending_approval", now=T1)
    store.write("ledger/set_claim_status", KEEPER, {
        "uid": other.uid, "from": ["pending_approval"], "to": "rejected", "now": T3})  # fmt: skip
    one = {"gap": "gap:1", "statuses": ["pending_approval"]}
    assert [r["uid"] for r in store.read("ledger/claims_for_gap", one)] == [pending.uid]
    both = {**one, "statuses": ["pending_approval", "rejected"]}
    got = [r["uid"] for r in store.read("ledger/claims_for_gap", both)]
    assert got == [other.uid, rejected.uid, pending.uid]  # most recently updated first
    assert store.read("ledger/claims_for_gap", {**one, "gap": "gap:2"}) == []
    assert store.read("ledger/claims_for_gap", both)[0]["gap"] == "gap:1"


def test_claim_status_records_the_conflict(store):
    """approve re-checks the sources: the move to conflicts_with_source carries what they say."""
    c = write_claim(store, status="pending_approval")
    move = {"uid": c.uid, "from": ["pending_approval"], "to": "conflicts_with_source", "now": T2}
    out = store.write("ledger/set_claim_status", KEEPER, {**move, "conflict": "owners: team:x"})
    assert out == [{"uid": c.uid, "status": "conflicts_with_source"}]
    [got] = store.read("ledger/get_claim", {"uid": c.uid})
    assert (got["status"], got["conflict"]) == ("conflicts_with_source", "owners: team:x")
    back = {**move, "from": ["conflicts_with_source"], "to": "superseded", "now": T3}
    store.write("ledger/set_claim_status", KEEPER, back)  # no conflict given: kept
    assert store.read("ledger/get_claim", {"uid": c.uid})[0]["conflict"] == "owners: team:x"


def test_back_to_pending_clears_the_approval(store):
    """An accept undone (the projection failed) waits for a lead again, unapproved."""
    c = write_claim(store, status="pending_approval")
    move = {"uid": c.uid, "from": ["pending_approval"], "to": "accepted", "by": "Dana", "now": T2}
    store.write("ledger/set_claim_status", KEEPER, move)
    back = {"uid": c.uid, "from": ["accepted"], "to": "pending_approval", "by": "Dana",
            "why": "projection failed", "now": T3}  # fmt: skip
    assert store.write("ledger/set_claim_status", KEEPER, back) == [
        {"uid": c.uid, "status": "pending_approval"}]  # fmt: skip
    [got] = store.read("ledger/get_claim", {"uid": c.uid})
    assert (got["status"], got["approved_by"], got["valid_from"], got["why"]) == (
        "pending_approval", None, None, "projection failed")  # fmt: skip


def test_queue_follow_up(store):
    owner = write_claim(store, "owner", "accepted", now=T1)
    conflict = write_claim(store, "fact", "conflicts_with_source", now=T2)
    write_claim(store, "fact", "accepted", now=T1)  # a plain fact needs no follow-up
    write_claim(store, "owner", "pending_approval", now=T1)  # not yet accepted
    queued = store.read("ledger/queue_follow_up", {})
    assert [r["uid"] for r in queued] == [owner.uid, conflict.uid]  # oldest first
    assert queued[0]["evidence"] == ["pr:1", "pr:2"]

    follow = {"claim": owner.uid, "title": "Follow up", "body": "Tell Alice.", "by": "pm"}
    assert store.write("ledger/open_followup", "citadel_pm", {**follow, "now": T2}) == [
        {"uid": f"followup:{owner.uid}", "created": True}]  # fmt: skip
    assert store.write("ledger/open_followup", "citadel_pm", {**follow, "now": T3}) == [
        {"uid": f"followup:{owner.uid}", "created": False}]  # fmt: skip
    assert [r["uid"] for r in store.read("ledger/queue_follow_up", {})] == [conflict.uid]

    [f] = store.read("ledger/followups", {"status": "open", "limit": 10})
    assert (f["uid"], f["claim"], f["title"], f["status"], f["created_at"]) == (
        f"followup:{owner.uid}", owner.uid, "Follow up", "open", T2)  # fmt: skip
    assert store.read("ledger/followups", {"status": "done", "limit": 10}) == []


def test_a_follow_up_tried_once_leaves_the_queue(store):
    """A pm follow-up job that ended with no decision is not paid for again on every review."""
    owner = write_claim(store, "owner", "accepted", now=T1)
    conflict = write_claim(store, "fact", "conflicts_with_source", now=T2)
    tried = {"claim": owner.uid, "now": T2}
    assert store.write("ledger/follow_up_tried", KEEPER, tried) == [
        {"uid": owner.uid, "follow_up_tries": 1}]  # fmt: skip
    assert [r["uid"] for r in store.read("ledger/queue_follow_up", {})] == [conflict.uid]
    assert store.write("ledger/follow_up_tried", KEEPER, {**tried, "now": T3}) == []  # once
    [got] = store.read("ledger/get_claim", {"uid": owner.uid})
    assert (got["follow_up_tries"], got["updated_at"]) == (1, T1)  # the claim did not change
    [other] = store.read("ledger/get_claim", {"uid": conflict.uid})
    assert other["follow_up_tries"] == 0
    assert store.write("ledger/follow_up_tried", KEEPER, {"claim": "claim:nope", "now": T2}) == []


def test_epoch_now_is_stored_as_iso(store):
    """Job writes go through roles.base.write, which passes Ctx.now: an epoch int."""
    epoch, at = 1_792_224_000, "2026-10-17T08:00:00Z"
    [g] = open_gap(store, "who owns billing", "t1", now=epoch)
    set_status(store, g["uid"], ["open"], "in_review", now=epoch + 60)
    gap = get_gap(store, g["uid"])
    assert (gap["created_at"], gap["updated_at"]) == (at, "2026-10-17T08:01:00Z")

    post = {"gap": g["uid"], "role": "qa", "attempt": 0, "now": epoch}
    store.write("ledger/post_consult", KEEPER, post)
    answer = {"consult": f"consult:{g['uid']}:qa:0", "can_ground": False, "now": epoch}
    store.write("ledger/answer_consult", "citadel_qa", answer)
    [c] = store.read("ledger/consults_for_gap", {"gap": g["uid"]})
    assert (c["created_at"], c["answered_at"]) == (at, at)


def test_write_claim_defaults_its_timestamps_to_now(store):
    fields = {"uid": "claim:t", "kind": "fact", "subject": "system:auth", "statement": "x"}
    store.write("ledger/write_claim", KEEPER, {**fields, "author": "keeper", "now": T2})
    [got] = store.read("ledger/get_claim", {"uid": "claim:t"})
    assert (got["created_at"], got["updated_at"], got["status"]) == (T2, T2, "pending_approval")


def test_bad_writes_are_refused_before_anything_is_stored(store):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        open_gap(store, "who owns billing", "t1", kind="bogus")
    assert store.read("ledger/gaps", {"statuses": ["open"], "limit": 10}) == []

    [g] = open_gap(store, "who owns billing", "t1")
    with pytest.raises(ValueError):
        set_status(store, g["uid"], ["open"], "closed")
    assert get_gap(store, g["uid"])["status"] == "open"

    with pytest.raises(ValidationError):  # no statement
        store.write("ledger/write_claim", KEEPER, {
            "uid": "claim:bad", "kind": "owner", "subject": "system:billing",
            "author": "keeper", "now": T1})  # fmt: skip
    with pytest.raises(ValidationError):
        store.write("ledger/write_claim", KEEPER, {
            "uid": "claim:bad", "kind": "rumour", "subject": "system:billing",
            "statement": "x", "author": "keeper", "now": T1})  # fmt: skip
    assert store.read("ledger/get_claim", {"uid": "claim:bad"}) == []

    c = write_claim(store, status="pending_approval")
    move = {"uid": c.uid, "from": ["pending_approval"], "to": "approved", "now": T2}
    with pytest.raises(ValueError):
        store.write("ledger/set_claim_status", KEEPER, move)
    assert store.read("ledger/get_claim", {"uid": c.uid})[0]["status"] == "pending_approval"
