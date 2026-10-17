"""Ask interviews a person about the brain's gaps; a reply is filed for a lead, never projected."""

from __future__ import annotations

import json

import pytest
from agents import ask as agent
from agents import loop
from agents.keeper.decide import approve, reject
from agents.keeper.interview import FROM_PERSON, Interview
from agents.keeper.model import gap_uid
from agents.keeper.store import MemoryKeeperStore
from agents.testing import (  # noqa: F401  (settings: autouse fixture)
    TOOLSET,
    FakeBrainFacts,
    FakeClient,
    reply,
    settings,
    submit,
    tool_use,
)
from agents.toolset import _collect_nodes, with_interview
from brain.keeper import SourceFacts
from langgraph.checkpoint.memory import InMemorySaver

SLUG = "synthetic"
NOW = "2026-10-17T10:00:00Z"
LATER = "2026-10-17T11:00:00Z"


def seed(store: MemoryKeeperStore, kind="stale_owner", subject="system:Auth", text=None,
         status="open", now=NOW) -> str:  # fmt: skip
    text = text or f"{kind} {subject}"
    noticing = kind in ("stale_owner", "unowned_hot_system")
    [row] = store.write("ledger/open_gap", "citadel_keeper", {
        "uid": gap_uid(), "kind": kind, "text": text, "now": now,
        "norm": None if noticing else text.lower(), "subject": subject if noticing else None,
        "about": [subject]})  # fmt: skip
    if status != "open":
        moved = {"uid": row["uid"], "from": ["open"], "to": status, "now": now}
        assert store.write("ledger/set_gap_status", "citadel_keeper", moved)
    return row["uid"]


def status(store, uid: str) -> str:
    return store.read("ledger/get_gap", {"uid": uid})[0]["status"]


@pytest.fixture
def store():
    return MemoryKeeperStore(SLUG)


@pytest.fixture
def brain():
    return FakeBrainFacts()


@pytest.fixture
def interview(store, brain):
    return Interview(lambda slug: store, brain, now=lambda: LATER)


# --- open_gaps ------------------------------------------------------------------------------


def test_open_gaps_offers_needs_person_first_then_open_in_pick_order(store, interview):
    noticed = seed(store, "stale_owner", "system:Billing")
    asked = seed(store, "failed_question", "system:Auth", text="Who owns Auth?")
    stuck = seed(store, "unowned_hot_system", "system:Infra", status="needs_person")
    seed(store, "stale_owner", "system:Web app", status="dismissed")
    seed(store, "stale_owner", "system:Auth", status="in_review")

    rows = interview.open_gaps(SLUG, limit=5)
    assert [r.gap for r in rows] == [stuck, asked, noticed]
    assert rows[0].subject_uid == "system:Infra" and rows[0].status == "needs_person"
    assert interview.open_gaps(SLUG, limit=1)[0].gap == stuck


def test_a_gap_row_lets_the_agent_cite_its_subject_but_never_the_gap(store, interview):
    seed(store, "stale_owner", "system:Billing")
    seen: dict = {}
    _collect_nodes([r.model_dump() for r in interview.open_gaps(SLUG)], seen)
    assert "system:Billing" in seen
    assert not any(u.startswith("gap:") for u in seen)


# --- record_testimony -----------------------------------------------------------------------


def test_a_reply_becomes_a_pending_claim_and_the_gap_waits_in_review(store, brain, interview):
    g = seed(store, "stale_owner", "system:Billing")
    row = interview.record_testimony(
        SLUG, gap=g, kind="owner", subject_uid="system:Billing",
        statement="erin owns Billing since the payments rewrite.", value="person:erin",
        cites=["fake:pr:3"])  # fmt: skip

    claim = store.claims[row.claim]
    assert (claim.status, claim.critical, claim.author) == ("pending_approval", True, "person")
    assert claim.critical_reasons[0] == FROM_PERSON
    assert (claim.gap, claim.value) == (g, "person:erin")
    assert claim.evidence == ["system:Billing", "fake:pr:3"]  # the subject, then the cites
    assert status(store, g) == "in_review"
    assert [(e.actor, e.action, e.claim) for e in store.log] == [("ask", "claim_queued", row.claim)]
    assert brain.project_calls == 0  # Ask never writes the brain


def test_even_a_sourced_reply_waits_for_a_lead(store, interview):
    """Source evidence would let the Keeper's own claim auto-accept; a person's never does."""
    row = interview.record_testimony(
        SLUG, gap=None, kind="fact", subject_uid="system:Auth",
        statement="Auth moved to JWT.", cites=["fake:pr:1"])  # fmt: skip
    assert row.status == "pending_approval" and row.critical_reasons == [FROM_PERSON]
    assert store.claims[row.claim].gap is None


def test_a_lead_approval_resolves_the_gap_and_a_rejection_reopens_it(store, brain, interview):
    g1 = seed(store, "stale_owner", "system:Billing")
    g2 = seed(store, "stale_owner", "system:Auth")
    one = interview.record_testimony(
        SLUG,
        gap=g1,
        kind="fact",
        subject_uid="system:Billing",
        statement="Billing runs nightly.",
        cites=["fake:pr:3"],
    )
    two = interview.record_testimony(
        SLUG,
        gap=g2,
        kind="fact",
        subject_uid="system:Auth",
        statement="Auth is frozen.",
        cites=["fake:pr:1"],
    )

    assert approve(store, SLUG, one.claim, "Dana", "Checked.", brain=brain).status == "accepted"
    assert status(store, g1) == "resolved" and brain.project_calls == 1
    reject(store, SLUG, two.claim, "Dana", "Not true.")
    after = store.read("ledger/get_gap", {"uid": g2})[0]
    assert (after["status"], after["attempts"]) == ("open", 1)


def test_a_reply_with_no_cites_is_accepted_when_a_lead_approves(store, brain, interview):
    """The person's word is the evidence: the subject is kept as evidence, so projection does
    not take the claim for one whose evidence is gone (stale)."""
    g = seed(store, "stale_owner", "system:Billing")
    row = interview.record_testimony(SLUG, gap=g, kind="fact", subject_uid="system:Billing",
                                     statement="Billing runs nightly.")  # fmt: skip
    assert "no_source_evidence" in row.critical_reasons
    assert approve(store, SLUG, row.claim, "Dana", None, brain=brain).status == "accepted"
    assert status(store, g) == "resolved"


def test_the_conflict_with_the_sources_is_said_but_the_lead_still_decides(store, brain,
                                                                         interview):  # fmt: skip
    brain.facts["system:Auth"] = SourceFacts(exists=True, declared_owners=["person:alice"])
    row = interview.record_testimony(
        SLUG,
        gap=None,
        kind="owner",
        subject_uid="system:Auth",
        statement="carol owns Auth.",
        value="person:carol",
    )
    assert row.conflict == "declared owners: person:alice"
    assert store.claims[row.claim].status == "pending_approval"


@pytest.mark.parametrize(
    ("params", "says"),
    [
        ({"subject_uid": "system:Nope", "kind": "fact"}, "Not nodes in the graph: system:Nope"),
        ({"subject_uid": "system:Auth", "kind": "fact", "cites": ["pr:999"]}, "pr:999"),
        ({"subject_uid": "system:Auth", "kind": "owner"}, "needs value"),
        ({"subject_uid": "system:Auth", "kind": "owner", "value": "person:zed"}, "needs value"),
        ({"subject_uid": "system:Auth", "kind": "fact", "gap": "gap:missing"}, "No gap"),
    ],
)
def test_refusals_write_nothing(store, interview, params, says):
    with pytest.raises(ValueError, match=says):
        interview.record_testimony(SLUG, **{"gap": None, "statement": "x", **params})
    assert store.claims == {} and store.log == []


def test_a_gap_already_decided_or_in_review_is_refused(store, interview):
    for gap_status, subject in (("in_review", "system:Auth"), ("dismissed", "system:Infra")):
        g = seed(store, "stale_owner", subject, status=gap_status)
        with pytest.raises(ValueError, match="not open"):
            interview.record_testimony(SLUG, gap=g, kind="fact", subject_uid="system:Auth",
                                       statement="x")  # fmt: skip
        assert status(store, g) == gap_status
    assert store.claims == {}


def test_a_missing_brain_is_refused(store, brain, interview):
    brain.exists = False
    with pytest.raises(ValueError, match="rebuilt"):
        interview.record_testimony(SLUG, gap=None, kind="fact", subject_uid="system:Auth",
                                   statement="x")  # fmt: skip


def test_a_failed_claim_write_gives_the_gap_back(store, interview, monkeypatch):
    g = seed(store, "stale_owner", "system:Auth", status="needs_person")
    real = store.write

    def failing(name, user, params):
        if name == "ledger/write_claim":
            raise RuntimeError("connection reset")
        return real(name, user, params)

    monkeypatch.setattr(store, "write", failing)
    with pytest.raises(RuntimeError):
        interview.record_testimony(SLUG, gap=g, kind="fact", subject_uid="system:Auth",
                                   statement="x")  # fmt: skip
    assert status(store, g) == "needs_person"


# --- through the Ask loop -------------------------------------------------------------------


def test_ask_me_questions_asks_then_files_the_reply(store, brain):
    """Turn 1 reads the gaps and asks, citing the gap's subject (so the turn is not a failed
    question). Turn 2 files the reply and asks the next one."""
    g = seed(store, "stale_owner", "system:Billing", text="Billing's declared owner is inactive")
    tools = with_interview(TOOLSET, lambda slug: store, brain)
    names = [d["name"] for d in tools.definitions()]
    assert names == sorted(names) and {"open_gaps", "record_testimony"} <= set(names)

    client = FakeClient(
        reply(tool_use("t1", "open_gaps", {})),
        reply(submit("t2", "Who owns Billing now [1]?", ["system:Billing"])),
        reply(
            tool_use(
                "t3",
                "record_testimony",
                {
                    "gap": g,
                    "kind": "owner",
                    "subject_uid": "system:Billing",
                    "statement": "erin owns Billing.",
                    "value": "person:erin",
                },
            )
        ),  # fmt: skip
        reply(
            submit("t4", "Filed for a lead to review [1]. No more questions.", ["system:Billing"])
        ),  # fmt: skip
    )
    saver = InMemorySaver()
    first = agent.ask(SLUG, "Ask me questions.", "th1", client=client, toolset=tools,
                      checkpointer=saver)  # fmt: skip
    assert first.text == "Who owns Billing now [1]?"
    assert [s.uid for s in first.sources] == ["system:Billing"]
    gaps = json.loads(client.requests[1]["messages"][-1]["content"][0]["content"])["rows"]
    assert [r["gap"] for r in gaps] == [g]

    second = agent.ask(SLUG, "erin does.", "th1", client=client, toolset=tools,
                       checkpointer=saver)  # fmt: skip
    filed = json.loads(client.requests[3]["messages"][-1]["content"][0]["content"])["rows"][0]
    assert filed["status"] == "pending_approval"
    assert second.stop == "tool_use" and second.sources[0].uid == "system:Billing"
    assert status(store, g) == "in_review" and brain.project_calls == 0


def test_the_prompt_tells_the_agent_to_ask_not_offer():
    prompt = loop.SYSTEM_PROMPT
    assert "`open_gaps`" in prompt and "`record_testimony`" in prompt
    assert "ask them questions" in prompt
