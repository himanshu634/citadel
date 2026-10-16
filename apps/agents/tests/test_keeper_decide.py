"""The Keeper's deterministic decide step, and a lead's approve and reject: evidence check,
sources win, the critical rule, accept / supersede / project / stale. Offline: `MemoryKeeperStore`
and `FakeBrainFacts`, no FalkorDB."""

from __future__ import annotations

import pytest
from agents.keeper.decide import ClaimNotPending, apply_decision, approve, reject
from agents.keeper.model import Gap, gap_uid, iso
from agents.keeper.store import MemoryKeeperStore
from agents.roles import ROLES, Ctx
from agents.testing import FakeBrainFacts
from agents.work.submits import SubmitKeeperDecision
from brain.keeper import SourceFacts

SLUG = "synthetic"
NOW = 1_790_000_000
LATER = NOW + 600
KEEPER = "citadel_keeper"
CTX = Ctx("agent:keeper-1", KEEPER, NOW)
ALL = ["pending_approval", "accepted", "rejected", "superseded", "stale", "conflicts_with_source"]


def seed_gap(store: MemoryKeeperStore, text: str = "Who owns Auth?") -> Gap:
    [row] = store.write(
        "ledger/open_gap",
        "citadel_brain",
        {"uid": gap_uid(), "kind": "failed_question", "text": text, "norm": text.lower(),
         "now": NOW - 60},
    )  # fmt: skip
    in_review(store, row["uid"])
    return gap(store, row["uid"])


def in_review(store, uid: str) -> None:
    move = {"uid": uid, "from": ["open"], "to": "in_review", "now": NOW - 50}
    assert store.write("ledger/set_gap_status", KEEPER, move)


def gap(store, uid: str) -> Gap:
    [g] = store.read("ledger/get_gap", {"uid": uid})
    return Gap(**g)


def claim_sub(g: Gap, **kw) -> SubmitKeeperDecision:
    fields = {
        "kind": "owner",
        "subject_uid": "system:Auth",
        "statement": "Alice owns Auth.",
        "value": "person:alice",
        "about": ["system:Auth"],
        "reason": "Alice merged most Auth changes.",
        "cites": ["fake:pr:2"],
        **kw,
    }
    return SubmitKeeperDecision(gap=g.uid, outcome="claim", **fields)


def claims(store, g: Gap) -> list[dict]:
    return store.read("ledger/claims_for_gap", {"gap": g.uid, "statuses": ALL})


def the_claim(store, g: Gap) -> dict:
    [c] = claims(store, g)
    return c


def actions(store, **where) -> list[str]:
    """The log's actions, oldest first, optionally for one gap or claim."""
    return [e.action for e in store.log if all(getattr(e, k) == v for k, v in where.items())]


def entries(store, action: str) -> list:
    return [e for e in store.log if e.action == action]


# --- decide ----------------------------------------------------------------------------------


def test_noncritical_claim_accepted_and_projected():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    g = seed_gap(store)
    rows = apply_decision(store, CTX, g, claim_sub(g), brain)
    c = the_claim(store, g)
    assert rows == [{"uid": c["uid"], "status": "accepted"}]
    assert (c["status"], c["critical"], c["critical_reasons"]) == ("accepted", False, [])
    assert (c["approved_by"], c["valid_from"], c["valid_to"]) == ("auto", iso(NOW), None)
    assert (c["author"], c["why"], c["evidence"]) == (
        "keeper", "Alice merged most Auth changes.", ["fake:pr:2"])  # fmt: skip
    assert c["about"] == ["system:Auth"] and c["gap"] == g.uid
    assert [p["uid"] for p in brain.projected] == [c["uid"]]
    assert brain.projected[0]["approved_by"] == "auto"  # the stored claim is projected
    assert gap(store, g.uid).status == "resolved"
    assert actions(store) == ["claim_written"]
    [e] = store.log
    assert (e.actor, e.gap, e.claim, e.evidence) == ("auto", g.uid, c["uid"], ["fake:pr:2"])


def test_conflict_with_source_not_projected():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    brain.facts["system:Auth"] = SourceFacts(exists=True, declared_owners=["team:identity"])
    g = seed_gap(store)
    rows = apply_decision(store, CTX, g, claim_sub(g), brain)
    c = the_claim(store, g)
    assert rows == [{"uid": c["uid"], "status": "conflicts_with_source"}]
    assert c["conflict"] == "declared owners: team:identity"
    assert brain.projected == [] and brain.project_calls == 0
    assert gap(store, g.uid).status == "resolved"
    assert actions(store) == ["claim_conflicts_with_source"]
    [e] = store.log
    assert "person:alice" in e.why and "team:identity" in e.why  # both sides


def test_critical_claim_queued():
    """The subject counts for the critical rule even when `about` leaves it out."""
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts(high_impact={"system:Auth"})
    g = seed_gap(store)
    rows = apply_decision(store, CTX, g, claim_sub(g, about=["person:alice"]), brain)
    c = the_claim(store, g)
    assert rows == [{"uid": c["uid"], "status": "pending_approval"}]
    assert (c["critical"], c["critical_reasons"]) == (True, ["high_impact_system"])
    assert c["about"] == ["system:Auth", "person:alice"]
    assert brain.project_calls == 0
    assert gap(store, g.uid).status == "in_review"
    assert actions(store) == ["claim_queued"]
    assert store.log[0].why == "high_impact_system"


def test_queue_skips_a_gap_waiting_for_a_lead():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts(high_impact={"system:Auth"})
    g = seed_gap(store)
    for role in ("pm", "qa"):
        post = {"gap": g.uid, "role": role, "attempt": 0, "now": NOW}
        store.write("ledger/post_consult", KEEPER, post)
        answer = {"consult": f"consult:{g.uid}:{role}:0", "can_ground": False, "now": NOW}
        store.write("ledger/answer_consult", f"citadel_{role}", answer)
    decide = ROLES["keeper"].job("decide")
    assert [s.uid for s in decide.queue(store, CTX)] == [g.uid]
    apply_decision(store, CTX, g, claim_sub(g), brain)
    assert the_claim(store, g)["status"] == "pending_approval"
    assert decide.queue(store, CTX) == []


def test_missing_evidence_rejected_and_attempts():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    g = seed_gap(store)
    sub = claim_sub(g, cites=["fake:pr:2", "fake:pr:gone"])
    [row] = apply_decision(store, CTX, g, sub, brain)
    c = the_claim(store, g)
    assert row == {"uid": c["uid"], "status": "rejected"}
    assert (c["status"], c["why"]) == ("rejected", "evidence_missing: fake:pr:gone")
    after = gap(store, g.uid)
    assert (after.status, after.attempts) == ("open", 1)
    assert actions(store) == ["claim_rejected"]

    in_review(store, g.uid)  # the next review takes it again
    apply_decision(store, CTX, gap(store, g.uid), sub, brain)
    after = gap(store, g.uid)
    assert (after.status, after.attempts) == ("needs_person", 2)
    assert actions(store) == ["claim_rejected", "claim_rejected"]
    assert brain.project_calls == 0


def test_supersedes_earlier_claim():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    first = seed_gap(store)
    apply_decision(store, CTX, first, claim_sub(first), brain)
    earlier = the_claim(store, first)
    assert earlier["status"] == "accepted"

    second = seed_gap(store, "Who owns Auth now?")
    sub = claim_sub(second, statement="Carol owns Auth.", value="person:carol")
    apply_decision(store, CTX, second, sub, brain)
    new = the_claim(store, second)
    assert (new["status"], new["critical_reasons"]) == ("pending_approval", ["replaces_claim"])

    got = approve(store, SLUG, new["uid"], "Dana", "Alice moved teams.", brain=brain, now=LATER)
    assert (got.status, got.approved_by, got.why) == ("accepted", "Dana", "Alice moved teams.")
    [old] = store.read("ledger/get_claim", {"uid": earlier["uid"]})
    assert (old["status"], old["valid_to"]) == ("superseded", iso(LATER))
    assert brain.retired == [(earlier["uid"], "superseded", iso(LATER))]
    assert [p["uid"] for p in brain.projected] == [earlier["uid"], new["uid"]]
    assert gap(store, second.uid).status == "resolved"
    assert actions(store) == ["claim_written", "claim_queued", "claim_superseded", "claim_approved"]
    [sup] = entries(store, "claim_superseded")
    assert (sup.claim, sup.actor) == (earlier["uid"], "Dana") and new["uid"] in sup.why


def test_approve_twice():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts(high_impact={"system:Auth"})
    g = seed_gap(store)
    apply_decision(store, CTX, g, claim_sub(g), brain)
    uid = the_claim(store, g)["uid"]
    approve(store, SLUG, uid, "Dana", None, brain=brain, now=LATER)
    with pytest.raises(ClaimNotPending):
        approve(store, SLUG, uid, "Eve", None, brain=brain, now=LATER)
    with pytest.raises(ClaimNotPending):
        reject(store, SLUG, uid, "Eve", "Too late.", now=LATER)
    with pytest.raises(ClaimNotPending):
        approve(store, SLUG, "claim:nope", "Eve", None, brain=brain, now=LATER)
    [e] = entries(store, "claim_approved")
    assert e.actor == "Dana"
    assert actions(store) == ["claim_queued", "claim_approved"]
    assert the_claim(store, g)["approved_by"] == "Dana"
    assert len(brain.projected) == 1


def test_approve_after_sources_changed():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts(high_impact={"system:Auth"})
    g = seed_gap(store)
    apply_decision(store, CTX, g, claim_sub(g), brain)
    uid = the_claim(store, g)["uid"]
    brain.facts["system:Auth"] = SourceFacts(exists=True, declared_owners=["team:identity"])
    got = approve(store, SLUG, uid, "Dana", "Looks right.", brain=brain, now=LATER)
    assert (got.status, got.conflict) == ("conflicts_with_source", "declared owners: team:identity")
    assert brain.project_calls == 0
    assert gap(store, g.uid).status == "resolved"
    assert actions(store) == ["claim_queued", "claim_conflicts_with_source"]
    assert entries(store, "claim_conflicts_with_source")[0].actor == "Dana"


def test_reject_reopens_gap():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts(high_impact={"system:Auth"})
    g = seed_gap(store)
    apply_decision(store, CTX, g, claim_sub(g), brain)
    uid = the_claim(store, g)["uid"]
    got = reject(store, SLUG, uid, "Dana", "Alice left.", now=LATER)
    assert (got.status, got.approved_by, got.why) == ("rejected", "Dana", "Alice left.")
    after = gap(store, g.uid)
    assert (after.status, after.attempts) == ("open", 1)
    assert actions(store) == ["claim_queued", "claim_rejected"]
    [e] = entries(store, "claim_rejected")
    assert (e.actor, e.claim, e.gap, e.why) == ("Dana", uid, g.uid, "Alice left.")
    assert brain.project_calls == 0


def test_second_reject_needs_a_person():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts(high_impact={"system:Auth"})
    g = seed_gap(store)
    for _ in range(2):
        apply_decision(store, CTX, gap(store, g.uid), claim_sub(g), brain)
        pending = [c for c in claims(store, g) if c["status"] == "pending_approval"]
        reject(store, SLUG, pending[0]["uid"], "Dana", "No.", now=LATER)
        if gap(store, g.uid).status == "open":
            in_review(store, g.uid)
    after = gap(store, g.uid)
    assert (after.status, after.attempts) == ("needs_person", 2)


def test_stale_on_projection_missing():
    """Evidence is there but the subject is not: projection reports the claim missing."""
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    g = seed_gap(store)
    sub = claim_sub(g, kind="fact", subject_uid="system:Gone", about=["system:Gone"], value=None)
    rows = apply_decision(store, CTX, g, sub, brain)
    c = the_claim(store, g)
    assert rows == [{"uid": c["uid"], "status": "stale"}]
    assert c["status"] == "stale" and brain.projected == [] and brain.project_calls == 1
    after = gap(store, g.uid)
    assert (after.status, after.attempts) == ("open", 0)
    assert actions(store) == ["claim_stale"]


# --- needs_person and dismiss ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "status", "action"),
    [("needs_person", "needs_person", "needs_person"), ("dismiss", "dismissed", "gap_dismissed")],
)
def test_outcomes_without_a_claim(outcome, status, action):
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    g = seed_gap(store)
    sub = SubmitKeeperDecision(gap=g.uid, outcome=outcome, reason="Nobody knows.")
    assert apply_decision(store, CTX, g, sub, brain) == [{"uid": g.uid, "status": status}]
    assert gap(store, g.uid).status == status
    assert actions(store) == [action]
    assert apply_decision(store, CTX, gap(store, g.uid), sub, brain) == []  # not in review
    assert actions(store) == [action]


def test_claim_on_a_gap_not_in_review_writes_nothing():
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    g = seed_gap(store)
    store.write("ledger/set_gap_status", KEEPER,
                {"uid": g.uid, "from": ["in_review"], "to": "dismissed", "now": NOW})  # fmt: skip
    assert apply_decision(store, CTX, gap(store, g.uid), claim_sub(g), brain) == []
    assert claims(store, g) == [] and store.log == []
