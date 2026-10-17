"""The Keeper's review run, offline: noticing, re-projection, then consult -> decide -> follow-up
through `runner.run_job` with the scripted policies, `MemoryKeeperStore`, the fake brain and
`FakeBrainFacts`. Nothing here calls FalkorDB or the API."""

from __future__ import annotations

import pytest
from agents.keeper.model import gap_uid
from agents.keeper.notice import notice
from agents.keeper.project import reproject
from agents.keeper.review import ReviewEvent, review
from agents.keeper.store import MemoryKeeperStore
from agents.policies import offline_client
from agents.testing import FakeBrainFacts, fake_brain
from brain.keeper import SourceFacts
from redis.exceptions import ResponseError

SLUG = "synthetic"
NOW = "2026-10-17T10:00:00Z"
KEEPER = "citadel_keeper"
ALL = ["pending_approval", "accepted", "rejected", "superseded", "stale", "conflicts_with_source"]
GROUNDED = "What caused the rotation race?"  # the fake brain relates one item: fake:pr:2


def clock():
    return NOW


def seed_gap(store, text: str, kind: str = "failed_question") -> str:
    [row] = store.write(
        "ledger/open_gap",
        "citadel_brain",
        {"uid": gap_uid(), "kind": kind, "text": text, "norm": text.lower(),
         "now": "2026-10-17T09:00:00Z"},
    )  # fmt: skip
    return row["uid"]


def seed_claim(store, status: str = "accepted", *, kind: str = "owner", subject="system:Auth",
               evidence=("fake:pr:2",), gap: str | None = None) -> str:  # fmt: skip
    uid = f"claim:{len(store.claims):012d}"
    store.write(
        "ledger/write_claim",
        KEEPER,
        {"uid": uid, "kind": kind, "subject": subject, "statement": "Alice owns Auth.",
         "value": "person:alice", "about": [subject], "evidence": list(evidence),
         "status": status, "author": "keeper", "gap": gap, "now": "2026-10-17T09:30:00Z"},
    )  # fmt: skip
    return uid


def gap_status(store, uid: str) -> str:
    return store.gaps[uid].status


def actions(store) -> list[str]:
    return [e.action for e in store.log]


def run_review(store, brain, *, budget=5, graph_run=fake_brain, **kw):
    events: list[ReviewEvent] = []
    r = review(
        store,
        SLUG,
        budget=budget,
        trigger="manual",
        client_for=offline_client,
        graph_run=graph_run,
        brain=brain,
        on_event=events.append,
        now=clock,
        **kw,
    )
    return r, events


# --- the run ----------------------------------------------------------------------------------


def test_review_end_to_end_offline():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    gap = seed_gap(store, GROUNDED)
    r, events = run_review(store, brain)
    assert (r.state, r.stop, r.trigger, r.budget) == ("done", None, "manual", 5)
    [c] = store.read("ledger/claims_for_gap", {"gap": gap, "statuses": ALL})
    assert c["status"] == "accepted" and c["evidence"] == ["fake:pr:2"]
    assert gap_status(store, gap) == "resolved"
    assert [p["uid"] for p in brain.projected] == [c["uid"]]
    log = actions(store)
    want = ["review_start", "consulted", "claim_written", "review_done"]
    assert [a for a in log if a in want] == [
        "review_start", "consulted", "consulted", "claim_written", "review_done"]  # fmt: skip
    assert log[0] == "review_start" and log[-1] == "review_done"
    assert events[0].kind == "start" and events[-1].kind == "done"
    assert any(e.kind == "step" and e.claim == c["uid"] for e in events)
    assert store.read("ledger/review_current", {})[0]["state"] == "done"


def test_stale_consults_from_an_earlier_attempt_are_ignored():
    """A reopened gap is asked again for its current attempt; the old open consult is left."""
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    gap = seed_gap(store, GROUNDED)
    old = {"gap": gap, "role": "pm", "attempt": 0, "now": "2026-10-17T09:10:00Z"}
    store.write("ledger/post_consult", KEEPER, old)
    store.write("ledger/set_gap_status", KEEPER, {"uid": gap, "from": ["open"], "to": "open",
                                                  "attempts_inc": 1, "now": NOW})  # fmt: skip
    runs: list[str] = []

    def client_for(role, job):
        runs.append(f"{role}.{job}")
        return offline_client(role, job)

    r = review(store, SLUG, budget=5, trigger="manual", client_for=client_for,
               graph_run=fake_brain, brain=brain, now=clock)  # fmt: skip
    assert r.state == "done"
    assert runs == ["pm.consult", "qa.consult", "keeper.decide"]
    by_attempt = {(c.role, c.attempt): c.status for c in store.consults.values()}
    assert by_attempt == {("pm", 0): "open", ("pm", 1): "answered", ("qa", 1): "answered"}
    assert gap_status(store, gap) == "resolved"


def test_review_respects_budget():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    gaps = [seed_gap(store, f"zzq unanswerable question {i}") for i in range(7)]
    r, _ = run_review(store, brain)
    assert r.state == "done"
    statuses = [gap_status(store, g) for g in gaps]
    assert statuses.count("open") == 2
    assert statuses.count("needs_person") == 5  # nothing grounds them: reviewed, not open


def test_one_review_at_a_time():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    seed_gap(store, GROUNDED)
    store.write("ledger/review_start", KEEPER, {"uid": "review:running", "trigger": "build",
                                                "budget": 3, "now": NOW})  # fmt: skip

    def no_client(role, job):
        raise AssertionError("no job may start while a review is running")

    events: list[ReviewEvent] = []
    r = review(store, SLUG, budget=5, trigger="manual", client_for=no_client,
               graph_run=fake_brain, brain=brain, on_event=events.append, now=clock)  # fmt: skip
    assert (r.uid, r.state) == ("review:running", "running")
    assert store.log == [] and events == [] and brain.project_calls == 0
    assert len(store.reviews) == 1


def test_brain_unavailable_stops():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts(exists=False)
    gap = seed_gap(store, GROUNDED)
    seed_claim(store)
    r, events = run_review(store, brain)
    assert (r.state, r.stop) == ("stopped", "brain_unavailable")
    assert gap_status(store, gap) == "open"
    assert brain.project_calls == 0  # nothing re-projected (or marked stale) on a missing brain
    assert [c.status for c in store.claims.values()] == ["accepted"]
    assert actions(store)[-1] == "review_stopped" and events[-1].kind == "stopped"


def test_brain_vanishes_mid_run_returns_gaps_to_open():
    """The brain goes missing during the first consult's tool loop: the loop turns the graph
    error into a tool result (so the policy answers can_ground False), but nothing is written
    and no further job starts."""
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    gaps = [seed_gap(store, GROUNDED), seed_gap(store, "zzq unanswerable")]

    def vanishing(slug, name, **params):
        brain.exists = False
        raise ResponseError("brain_synthetic: no such graph")

    r, _ = run_review(store, brain, graph_run=vanishing)
    assert (r.state, r.stop) == ("stopped", "brain_unavailable")
    assert [gap_status(store, g) for g in gaps] == ["open", "open"]
    assert [store.gaps[g].attempts for g in gaps] == [0, 0]  # no attempt used up
    assert {c.status for c in store.consults.values()} == {"open"}  # no answer recorded
    assert "consult_answered" not in actions(store)
    assert actions(store).count("episode") == 1  # the one run that started, its write refused


def test_orphaned_in_review_gaps_are_released_first():
    """A review killed mid-run leaves gaps in review; the next run sends them back to open,
    except one whose claim waits for a lead."""
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    orphan, waiting = seed_gap(store, GROUNDED), seed_gap(store, "zzq waiting for a lead")
    for g in (orphan, waiting):
        store.write("ledger/set_gap_status", KEEPER,
                    {"uid": g, "from": ["open"], "to": "in_review", "now": NOW})  # fmt: skip
    seed_claim(store, "pending_approval", gap=waiting)
    r, events = run_review(store, brain, budget=0)
    assert r.state == "done"
    assert (gap_status(store, orphan), gap_status(store, waiting)) == ("open", "in_review")
    assert store.gaps[orphan].attempts == 0
    [e] = [e for e in store.log if e.action == "gap_released"]
    assert e.gap == orphan and actions(store).index("gap_released") == 1  # right after start
    assert any(ev.step == "release" for ev in events)


def test_a_failure_before_the_steps_still_finishes_the_review():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()

    def on_event(e):
        if e.kind == "start":
            raise RuntimeError("stream closed")

    r = review(store, SLUG, budget=5, trigger="manual", client_for=offline_client,
               graph_run=fake_brain, brain=brain, on_event=on_event, now=clock)  # fmt: skip
    assert r.state == "failed" and "stream closed" in r.stop
    assert store.read("ledger/review_current", {})[0]["state"] == "failed"
    assert actions(store)[-1] == "review_failed"


def test_falkordb_error_inside_a_job_stops():
    """run_job swallows job errors; the review still sees a FalkorDB error in decide's apply."""

    class Failing(FakeBrainFacts):
        def evidence(self, slug, uids):
            raise ResponseError("brain_synthetic: graph gone")

    store, brain = MemoryKeeperStore(SLUG), Failing()
    gap = seed_gap(store, GROUNDED)
    r, _ = run_review(store, brain)
    assert (r.state, r.stop) == ("stopped", "brain_unavailable")
    assert gap_status(store, gap) == "open" and store.gaps[gap].attempts == 0
    assert store.claims == {}


def test_stop_between_jobs():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    gaps = [seed_gap(store, GROUNDED), seed_gap(store, "zzq unanswerable")]
    runs: list[str] = []

    def client_for(role, job):
        runs.append(f"{role}.{job}")
        return offline_client(role, job)

    r = review(store, SLUG, budget=5, trigger="manual", client_for=client_for,
               graph_run=fake_brain, brain=brain, should_stop=lambda: bool(runs),
               now=clock)  # fmt: skip
    assert (r.state, r.stop) == ("stopped", "requested")
    assert len(runs) == 1  # stopped after the first job
    assert [gap_status(store, g) for g in gaps] == ["open", "open"]  # back for the next review
    assert actions(store)[-1] == "review_stopped"


def test_other_errors_fail():
    def broken(role, job):
        raise RuntimeError("no client today")

    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    gap = seed_gap(store, GROUNDED)
    r = review(store, SLUG, budget=5, trigger="manual", client_for=broken,
               graph_run=fake_brain, brain=brain, now=clock)  # fmt: skip
    assert r.state == "failed" and "no client today" in r.stop
    assert gap_status(store, gap) == "open"
    assert actions(store)[-1] == "review_failed"


def test_budget_zero_reprojects_notices_and_follows_up():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    brain.notices["stale_owner"] = [
        {"subject": "system:Billing", "about": ["system:Billing"], "text": "Billing is stale."}
    ]
    gap = seed_gap(store, GROUNDED)
    claim = seed_claim(store)
    r, _ = run_review(store, brain, budget=0)
    assert r.state == "done"
    assert [p["uid"] for p in brain.projected] == [claim]
    assert gap_status(store, gap) == "open" and store.consults == {}  # nothing reviewed
    [f] = store.read("ledger/followups", {"limit": 5})
    assert f["claim"] == claim
    assert [g.kind for g in store.gaps.values()].count("stale_owner") == 1


def test_follow_up_without_a_decision_runs_once():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    seed_claim(store)  # projected, but pm finds nothing to cite in its run
    runs: list[str] = []

    def client_for(role, job):
        runs.append(f"{role}.{job}")
        return offline_client(role, job)

    def nothing(slug, name, **params):
        return []

    r = review(store, SLUG, budget=0, trigger="approval", client_for=client_for,
               graph_run=nothing, brain=brain, now=clock)  # fmt: skip
    assert r.state == "done"
    assert runs == ["pm.follow_up"]
    assert store.read("ledger/followups", {"limit": 5}) == []


# --- noticing ---------------------------------------------------------------------------------


def _rows(*subjects: str) -> list[dict]:
    return [{"subject": s, "about": [s], "text": f"{s} looks stale."} for s in subjects]


def test_notice_skips_settled_subjects():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    brain.notices["stale_owner"] = _rows("system:Auth", "system:Billing", "system:Web app")
    brain.notices["unowned_hot_system"] = _rows("system:Infra")
    seed_claim(store, "accepted", subject="system:Auth")  # settled by an accepted owner claim
    fixing = seed_claim(store, "conflicts_with_source", subject="system:Billing")
    store.write("ledger/open_followup", "citadel_pm",
                {"claim": fixing, "title": "Fix CODEOWNERS", "now": NOW})  # fmt: skip
    seed_claim(store, "accepted", kind="fact", subject="system:Web app")  # not an owner claim

    new = notice(store, SLUG, cap=10, brain=brain, now=NOW)
    assert [store.gaps[u].subject for u in new] == ["system:Web app", "system:Infra"]
    assert [store.gaps[u].kind for u in new] == ["stale_owner", "unowned_hot_system"]
    opened = [e for e in store.log if e.action == "gap_opened"]
    assert [e.gap for e in opened] == new


def test_notice_skips_subjects_whose_latest_gap_is_settled():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    subjects = ["system:A", "system:B", "system:C", "system:D", "system:E"]
    brain.notices["stale_owner"] = _rows(*subjects)
    first = notice(store, SLUG, cap=10, brain=brain, now=NOW)
    for uid, to in zip(first, ["resolved", "dismissed", "needs_person", "in_review"], strict=False):
        store.write("ledger/set_gap_status", KEEPER,
                    {"uid": uid, "from": ["open"], "to": to, "now": NOW})  # fmt: skip
    # system:E's gap is still open: it is bumped, not opened again; system:D's is in review
    assert notice(store, SLUG, cap=10, brain=brain, now=NOW) == []
    assert len(store.gaps) == 5
    assert [store.gaps[u].count for u in first] == [1, 1, 1, 2, 2]
    # an unowned_hot_system gap about system:A is a different kind: not settled by the first
    brain.notices = {"unowned_hot_system": _rows("system:A")}
    assert len(notice(store, SLUG, cap=10, brain=brain, now=NOW)) == 1


def test_notice_cap():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    brain.notices["stale_owner"] = _rows("system:A", "system:B", "system:C")
    brain.notices["unowned_hot_system"] = _rows("system:D", "system:E", "system:F")
    new = notice(store, SLUG, cap=4, brain=brain, now=NOW)
    assert len(new) == 4 and len(store.gaps) == 4
    assert brain.notice_limits == [4, 4]  # each query asks for at most the cap
    # a second pass finds the same subjects: their gaps are bumped, no new one counts
    again = notice(store, SLUG, cap=4, brain=brain, now=NOW)
    assert len(again) == 2  # system:E and system:F, which the cap left out
    assert len(store.gaps) == 6
    assert max(g.count for g in store.gaps.values()) == 2


# --- re-projection ----------------------------------------------------------------------------


def test_reproject_superseded_by_source():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    claim = seed_claim(store)
    brain.facts["system:Auth"] = SourceFacts(exists=True, declared_owners=["team:identity"])
    out = reproject(store, SLUG, brain=brain, now=NOW)
    assert out == {"projected": 0, "stale": 0, "superseded_by_source": 1}
    c = store.claims[claim]
    assert (c.status, c.valid_to) == ("superseded", NOW)
    assert brain.projected == [] and brain.retired == [(claim, "superseded", NOW)]
    [e] = [e for e in store.log if e.action == "claim_superseded"]
    assert e.claim == claim and e.why == "source: declared owners: team:identity"


def test_reproject_logs_before_retiring():
    class Ordered(FakeBrainFacts):
        def retire(self, slug, uid, status, valid_to):
            assert [e.claim for e in store.log if e.action == f"claim_{status}"] == [uid]
            super().retire(slug, uid, status, valid_to)

    store, brain = MemoryKeeperStore(SLUG), Ordered()
    superseded = seed_claim(store)
    stale = seed_claim(store, kind="fact", subject="system:Billing", evidence=("fake:pr:404",))
    brain.facts["system:Auth"] = SourceFacts(exists=True, declared_owners=["team:identity"])
    reproject(store, SLUG, brain=brain, now=NOW)
    assert [u for u, *_ in brain.retired] == [superseded, stale]


def test_reproject_projects_and_marks_stale():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    gap = seed_gap(store, GROUNDED)
    store.write("ledger/set_gap_status", KEEPER,
                {"uid": gap, "from": ["open"], "to": "resolved", "now": NOW})  # fmt: skip
    kept = seed_claim(store)
    gone = seed_claim(store, kind="fact", subject="system:Billing", evidence=("fake:pr:404",),
                      gap=gap)  # fmt: skip
    out = reproject(store, SLUG, brain=brain, now=NOW)
    assert out == {"projected": 1, "stale": 1, "superseded_by_source": 0}
    assert [p["uid"] for p in brain.projected] == [kept]
    assert (store.claims[kept].status, store.claims[gone].status) == ("accepted", "stale")
    assert gap_status(store, gap) == "open" and store.gaps[gap].attempts == 0
    assert (gone, "stale", NOW) in brain.retired
    assert [e.claim for e in store.log if e.action == "claim_stale"] == [gone]


def test_reproject_refuses_a_missing_brain():
    from agents.keeper.decide import BrainUnavailable

    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts(exists=False)
    seed_claim(store)
    with pytest.raises(BrainUnavailable):
        reproject(store, SLUG, brain=brain, now=NOW)
    assert brain.project_calls == 0 and store.log == []
