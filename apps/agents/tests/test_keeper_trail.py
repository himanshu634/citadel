"""The work behind one claim (`agents.keeper.trail`): an offline review's steps cut into the pm,
qa and keeper jobs of the claim's gap, with the consults and the gap's log."""

from __future__ import annotations

from agents.keeper.model import Claim, ReviewStep
from agents.keeper.store import MemoryKeeperStore
from agents.keeper.trail import claim_trail, gap_of, jobs_of
from agents.testing import FakeBrainFacts

from .test_keeper_review import ALL, GROUNDED, run_review, seed_claim, seed_gap

SLUG = "synthetic"


def step(n: int, actor: str, tool: str, kind: str = "graph", **input) -> ReviewStep:
    return ReviewStep(review="review:1", n=n, actor=actor, tool=tool, kind=kind, input=input,
                      status="done", started_at="2026-10-17T10:00:00Z")  # fmt: skip


def test_gap_of_reads_gaps_and_consults():
    assert gap_of("gap:abc") == "gap:abc"
    assert gap_of("consult:gap:abc:pm:0") == "gap:abc"
    assert gap_of("claim:abc") is None


def test_jobs_end_at_their_actors_submit():
    steps = [
        step(1, "pm", "get_entity"),
        step(2, "pm", "work_history"),
        step(3, "pm", "submit_consult", "submit", subject="consult:gap:a:pm:0"),
        step(4, "keeper", "get_entity"),
        step(5, "keeper", "submit_keeper_decision", "submit", subject="gap:a"),
    ]
    jobs = jobs_of(list(reversed(steps)))
    assert [(s.tool, [g.n for g in graph]) for s, graph in jobs] == [
        ("submit_consult", [1, 2]),
        ("submit_keeper_decision", [4]),
    ]


def test_a_reviewed_claim_shows_pm_qa_and_keeper_work():
    store = MemoryKeeperStore(SLUG)
    gap = seed_gap(store, GROUNDED)
    other = seed_gap(store, "Who owns billing?")
    r, _ = run_review(store, FakeBrainFacts())
    [row] = store.read("ledger/claims_for_gap", {"gap": gap, "statuses": ALL})
    trail = claim_trail(store, Claim(**row))
    assert trail.review is not None and trail.review.uid == r.uid
    assert [j.actor for j in trail.jobs] == ["pm", "qa", "keeper"]
    assert all(j.steps for j in trail.jobs)
    assert all(gap_of(str(j.submit["subject"])) == gap for j in trail.jobs)
    pm, qa, keeper = trail.jobs
    assert pm.consult is not None and pm.consult.role == "pm" and pm.consult.can_ground
    assert qa.consult is not None and qa.consult.role == "qa"
    assert keeper.consult is None and keeper.submit["claim"] == row["uid"]
    assert {e.gap for e in trail.log} == {gap} and other not in {e.gap for e in trail.log}
    assert "claim_written" in [e.action for e in trail.log]
    assert trail.log == sorted(trail.log, key=lambda e: e.at)


def test_a_claim_no_review_picked_has_only_its_log():
    store = MemoryKeeperStore(SLUG)
    gap = seed_gap(store, "Who owns Auth?")
    uid = seed_claim(store, "pending_approval", gap=gap)
    trail = claim_trail(store, Claim(**store.read("ledger/get_claim", {"uid": uid})[0]))
    assert (trail.review, trail.jobs) == (None, [])


def test_a_claim_without_a_gap_has_no_trail():
    store = MemoryKeeperStore(SLUG)
    uid = seed_claim(store, "pending_approval")
    trail = claim_trail(store, Claim(**store.read("ledger/get_claim", {"uid": uid})[0]))
    assert (trail.claim, trail.review, trail.jobs, trail.log) == (uid, None, [], [])
