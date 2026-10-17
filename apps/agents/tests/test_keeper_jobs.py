"""The Keeper's agent jobs, offline: pm/qa consult, keeper decide and pm follow-up, run by
`runner.run_job` with the scripted policies, `MemoryKeeperStore` and the fake brain."""

from __future__ import annotations

import pytest
from agents.keeper.model import gap_uid
from agents.keeper.store import MemoryKeeperStore
from agents.policies import POLICIES, offline_client
from agents.roles import ROLES, Ctx
from agents.runner import missing_tools, run_job
from agents.testing import ITEMS, FakeBrainFacts, fake_brain
from agents.work.submits import SUBMITS, SubmitConsult, SubmitFollowUp, SubmitKeeperDecision
from pydantic import ValidationError

NOW = 1_790_000_000
SLUG = "synthetic"
FAKE_UIDS = {u for u, *_ in ITEMS}


def ctx(role: str) -> Ctx:
    return Ctx(f"agent:{role}-1", ROLES[role].db_user, NOW)


def no_rows(slug, name, **params):
    return []


def seed_gap(store: MemoryKeeperStore, text: str, roles=("pm", "qa")) -> str:
    [row] = store.write(
        "ledger/open_gap",
        "citadel_brain",
        {"uid": gap_uid(), "kind": "failed_question", "text": text, "norm": text.lower(),
         "now": NOW - 60},
    )  # fmt: skip
    gap = row["uid"]
    store.write(
        "ledger/set_gap_status",
        "citadel_keeper",
        {"uid": gap, "from": ["open"], "to": "in_review", "now": NOW - 50},
    )
    for role in roles:
        store.write(
            "ledger/post_consult",
            "citadel_keeper",
            {"gap": gap, "role": role, "attempt": 0, "now": NOW - 40},
        )
    return gap


def run(store, role: str, job: str, graph_run=fake_brain):
    r, j = ROLES[role], ROLES[role].job(job)
    [subject] = j.queue(store, ctx(role))
    return run_job(
        store, r, j, subject, ctx(role), client=offline_client(role, job), graph_run=graph_run
    )


@pytest.fixture
def facts(monkeypatch):
    """The decide job's brain facts, faked (the job's apply has no brain argument)."""
    from agents.keeper import decide

    fake = FakeBrainFacts()
    monkeypatch.setattr(decide, "DEFAULT_BRAIN", fake)
    return fake


def consults(store, gap):
    return {c["role"]: c for c in store.read("ledger/consults_for_gap", {"gap": gap})}


# --- registry ---------------------------------------------------------------------------------


def test_roles_listed():
    assert "keeper" in ROLES
    keeper = ROLES["keeper"]
    assert keeper.db_user == "citadel_keeper"
    assert keeper.read_tools == (
        "experts_for_system",
        "get_entity",
        "keeper_notes",
        "owners_vs_experts",
        "person_profile",
        "related_documents",
        "related_work_items",
        "work_history",
    )
    assert missing_tools(keeper) == []
    assert [j.name for j in keeper.jobs] == ["decide"]
    assert [j.name for j in ROLES["pm"].jobs] == ["consult", "follow_up"]
    assert [j.name for j in ROLES["qa"].jobs] == ["consult"]
    for role in ("pm", "qa"):
        assert "keeper_notes" in ROLES[role].read_tools
    for key in (("pm", "consult"), ("qa", "consult"), ("keeper", "decide"), ("pm", "follow_up")):
        assert key in POLICIES
    for s in (SubmitConsult, SubmitKeeperDecision, SubmitFollowUp):
        assert SUBMITS[s.name] is s


def test_submit_validators():
    base = {"gap": "gap:1", "reason": "r", "kind": "fact", "subject_uid": "fake:pr:2",
            "about": ["fake:pr:2"], "cites": ["fake:pr:2"]}  # fmt: skip
    with pytest.raises(ValidationError):
        SubmitKeeperDecision(outcome="claim", **base)  # no statement
    with pytest.raises(ValidationError):
        SubmitKeeperDecision(outcome="claim", **{**base, "statement": "s", "about": []})
    with pytest.raises(ValidationError):
        SubmitKeeperDecision(outcome="claim", **{**base, "statement": "s", "cites": []})
    ok = SubmitKeeperDecision(outcome="claim", statement="s", value="person:alice", **base)
    assert set(ok.uids()) == {"fake:pr:2", "person:alice"}
    assert SubmitKeeperDecision(gap="gap:1", outcome="needs_person", reason="r").uids() == []
    # outside a claim, only the cites are checked: leftover draft fields are not uids
    for outcome in ("needs_person", "dismiss"):
        stray = SubmitKeeperDecision(outcome=outcome, value="person:x", **base)
        assert stray.uids() == ["fake:pr:2"]

    with pytest.raises(ValidationError):
        SubmitConsult(consult="c", can_ground=True, kind="fact", subject_uid="x:1", cites=["x:1"])
    with pytest.raises(ValidationError):
        SubmitConsult(consult="c", can_ground=True, kind="fact", subject_uid="x:1", statement="s")
    c = SubmitConsult(
        consult="c", can_ground=True, kind="owner", subject_uid="system:Auth", statement="s",
        value="person:alice", cites=["fake:pr:2"],
    )  # fmt: skip
    assert set(c.uids()) == {"fake:pr:2", "system:Auth", "person:alice"}
    plain = SubmitConsult(consult="c", can_ground=True, kind="fact", subject_uid="x:1",
                          statement="s", value="plain text", cites=["x:2"])  # fmt: skip
    assert plain.uids() == ["x:2", "x:1"]
    assert SubmitConsult(consult="c", can_ground=False).uids() == []
    stray = SubmitConsult(consult="c", can_ground=False, subject_uid="x:1", value="person:x",
                          cites=["x:2"])  # fmt: skip
    assert stray.uids() == ["x:2"]  # not grounded: only the cites are checked

    with pytest.raises(ValidationError):
        SubmitFollowUp(claim="claim:1", title="t", body="b", cites=[])
    with pytest.raises(ValidationError):
        SubmitFollowUp(claim="claim:1", title="x" * 121, body="b", cites=["fake:pr:2"])


# --- consult ----------------------------------------------------------------------------------


def test_consult_job_grounded():
    store = MemoryKeeperStore(SLUG)
    gap = seed_gap(store, "Why did the auth refresh token race happen?")
    result = run(store, "pm", "consult")
    assert result.stop is None, result
    assert result.tools_called == ["related_work_items", "get_entity"]  # the system, re-read
    c = consults(store, gap)["pm"]
    assert c["status"] == "answered" and c["can_ground"] is True
    assert c["kind"] == "fact" and c["subject"] == "system:Auth"  # the first row's system
    assert c["cites"] and set(c["cites"]) <= FAKE_UIDS
    assert "refresh token rotation race" in c["statement"]
    assert consults(store, gap)["qa"]["status"] == "open"  # pm answered only its own
    log = store.read("ledger/read_log", {"gap": gap, "limit": 10})
    assert [e["action"] for e in log] == ["consult_answered"]
    assert log[0]["actor"] == "pm" and log[0]["evidence"] == c["cites"]


def test_consult_job_cannot_ground():
    store = MemoryKeeperStore(SLUG)
    gap = seed_gap(store, "Why did the auth refresh token race happen?")
    result = run(store, "qa", "consult", graph_run=no_rows)
    assert result.stop is None, result
    c = consults(store, gap)["qa"]
    assert c["status"] == "answered" and c["can_ground"] is False
    assert c["cites"] == [] and c["statement"] is None


def test_consult_queue_is_per_role_and_empties():
    store = MemoryKeeperStore(SLUG)
    seed_gap(store, "Why did the auth refresh token race happen?", roles=("qa",))
    assert ROLES["pm"].job("consult").queue(store, ctx("pm")) == []
    run(store, "qa", "consult")
    assert ROLES["qa"].job("consult").queue(store, ctx("qa")) == []


# --- decide -----------------------------------------------------------------------------------


def test_decide_queue_waits_for_every_consult():
    store = MemoryKeeperStore(SLUG)
    gap = seed_gap(store, "Why did the auth refresh token race happen?")
    seed_gap(store, "an in-review gap with no consults", roles=())
    decide = ROLES["keeper"].job("decide")
    assert decide.queue(store, ctx("keeper")) == []
    run(store, "pm", "consult")
    assert decide.queue(store, ctx("keeper")) == []
    run(store, "qa", "consult")
    assert [s.uid for s in decide.queue(store, ctx("keeper"))] == [gap]


def test_keeper_decide_needs_person():
    store = MemoryKeeperStore(SLUG)
    gap = seed_gap(store, "Who decided to move billing to Stripe?")
    run(store, "pm", "consult", graph_run=no_rows)
    run(store, "qa", "consult", graph_run=no_rows)
    result = run(store, "keeper", "decide")
    assert result.stop is None, result
    assert result.submit["outcome"] == "needs_person"
    [g] = store.read("ledger/get_gap", {"uid": gap})
    assert g["status"] == "needs_person" and g["reason"]
    actions = [e["action"] for e in store.read("ledger/read_log", {"gap": gap, "limit": 20})]
    assert "needs_person" in actions
    assert actions[0] == "episode"  # the runner's Episode, linked to the gap


def test_keeper_decide_claim_is_accepted(facts):
    """Grounded consults make the policy claim; the deterministic check accepts it."""
    store = MemoryKeeperStore(SLUG)
    gap = seed_gap(store, "Why did the auth refresh token race happen?")
    run(store, "pm", "consult")
    run(store, "qa", "consult")
    result = run(store, "keeper", "decide")
    sub = result.submit
    assert sub["outcome"] == "claim" and sub["gap"] == gap
    assert sub["subject_uid"] == "system:Auth" and sub["about"] == ["system:Auth"]
    assert set(sub["cites"]) <= FAKE_UIDS
    assert set(result.tools_called) == {"related_work_items", "get_entity"}
    assert result.stop is None, result
    [g] = store.read("ledger/get_gap", {"uid": gap})
    assert g["status"] == "resolved"
    [c] = store.read("ledger/claims_for_gap", {"gap": gap, "statuses": ["accepted"]})
    assert c["evidence"] == sub["cites"] and [p["uid"] for p in facts.projected] == [c["uid"]]


def test_decide_dismiss_and_refused_write():
    from agents.roles.keeper import apply_decide

    store = MemoryKeeperStore(SLUG)
    gap = seed_gap(store, "noise", roles=())
    subject = _gap_subject(store, gap)
    sub = SubmitKeeperDecision(gap=gap, outcome="dismiss", reason="Not a question.")
    rows = apply_decide(store, ctx("keeper"), subject, sub)
    assert rows == [{"uid": gap, "status": "dismissed"}]
    actions = [e["action"] for e in store.read("ledger/read_log", {"gap": gap, "limit": 5})]
    assert actions == ["gap_dismissed"]
    assert apply_decide(store, ctx("keeper"), subject, sub) == []  # no longer in review
    assert len(store.read("ledger/read_log", {"gap": gap, "limit": 5})) == 1


def _gap_subject(store, gap):
    from agents.roles import Subject

    [g] = store.read("ledger/get_gap", {"uid": gap})
    return Subject("gap", gap, g)


# --- follow-up --------------------------------------------------------------------------------


def _claim(store, status: str, kind: str = "owner") -> str:
    uid = "claim:abc123def456"
    store.write(
        "ledger/write_claim",
        "citadel_keeper",
        {"uid": uid, "kind": kind, "subject": "system:Auth", "statement": "Alice owns Auth.",
         "value": "person:alice", "about": ["system:Auth"], "evidence": ["fake:pr:2"],
         "status": status, "author": "keeper", "now": NOW - 10,
         **({"conflict": "CODEOWNERS says identity"} if status == "conflicts_with_source" else {})},
    )  # fmt: skip
    return uid


def test_follow_up_with_nothing_to_cite_gives_no_answer():
    """Neither evidence nor subject found again: no submit with empty cites, no retry loop."""
    store = MemoryKeeperStore(SLUG)
    _claim(store, "accepted")
    client = offline_client("pm", "follow_up")
    r, j = ROLES["pm"], ROLES["pm"].job("follow_up")
    [subject] = j.queue(store, ctx("pm"))
    result = run_job(store, r, j, subject, ctx("pm"), client=client, graph_run=no_rows)
    assert result.submit is None and result.rows == []  # ended without a decision
    assert result.stop == "end_turn"  # the policy's plain-text reply, after one nudge
    assert result.tools_called == ["get_entity", "get_entity"]  # one round: evidence + subject
    assert client.calls == 3  # tools, then no decision, then the one nudge
    assert store.read("ledger/followups", {"limit": 5}) == []


@pytest.mark.parametrize(
    ("status", "prefix"),
    [("accepted", "Follow up: "), ("conflicts_with_source", "Fix the source: ")],
)
def test_follow_up_job(status, prefix):
    store = MemoryKeeperStore(SLUG)
    claim = _claim(store, status)
    result = run(store, "pm", "follow_up")
    assert result.stop is None, result
    assert "get_entity" in result.tools_called
    [f] = store.read("ledger/followups", {"limit": 5})
    assert f["claim"] == claim and f["title"] == prefix + "Alice owns Auth."
    assert result.submit["cites"] == ["fake:pr:2"]
    assert ROLES["pm"].job("follow_up").queue(store, ctx("pm")) == []
    actions = [e["action"] for e in store.read("ledger/read_log", {"claim": claim, "limit": 5})]
    assert "follow_up_opened" in actions


def test_consult_without_systems_falls_back_to_the_row():
    def no_systems(slug, name, **params):
        rows = fake_brain(slug, name, **params)
        return [{**r, "systems": []} for r in rows] if name == "related_work_items" else rows

    store = MemoryKeeperStore(SLUG)
    gap = seed_gap(store, "Why did the auth refresh token race happen?")
    result = run(store, "pm", "consult", graph_run=no_systems)
    assert result.stop is None, result
    c = consults(store, gap)["pm"]
    assert c["subject"] in FAKE_UIDS and c["subject"] == c["cites"][0]


def test_keeper_decide_claims_from_the_search_alone(facts):
    """A brain that only answers the search (get_entity finds nothing) still grounds the claim."""

    def search_only(slug, name, **params):
        return fake_brain(slug, name, **params) if name == "related_work_items" else []

    store = MemoryKeeperStore(SLUG)
    seed_gap(store, "Why did the auth refresh token race happen?")
    run(store, "pm", "consult", graph_run=search_only)
    run(store, "qa", "consult", graph_run=search_only)
    result = run(store, "keeper", "decide", graph_run=search_only)
    assert result.submit["outcome"] == "claim" and set(result.submit["cites"]) <= FAKE_UIDS
    assert result.stop is None, result
    assert len(facts.projected) == 1
