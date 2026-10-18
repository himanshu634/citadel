"""The Keeper and the Archivist: a decide that asks the Archivist, the review's archive step
that runs the Keeper's requests and settles their gaps, and the fresh consult round a gap gets
when the Archivist found its history.

Offline: `MemoryKeeperStore`, the scripted policies, the fake brain and `FakeBrainFacts`, with
`answer_request` replaced by a fake that records the outcome it is given. The one graph test
(`test_review_runs_archivist_and_reopens_gap`) ingests the synthetic company into a throwaway
brain_archtest_keeper_<hex> under a temp repo root and deletes it afterwards.
"""

from __future__ import annotations

import shutil
import uuid
from typing import Any

import pytest
from agents.archivist.rules import norm
from agents.keeper import decide as keeper_decide
from agents.keeper import review as review_module
from agents.keeper.decide import apply_decision
from agents.keeper.model import ArchiveRequest, Gap, archive_uid, gap_uid
from agents.keeper.review import review
from agents.keeper.store import MemoryKeeperStore
from agents.policies import POLICIES, Results, ScriptedClient, offline_client
from agents.policies import keeper as keeper_policy
from agents.roles import ROLES, Ctx, Subject
from agents.testing import FakeBrainFacts, fake_brain
from agents.work.submits import SubmitKeeperDecision
from brain import config, db
from brain.config import get_settings
from brain.testing import SYNTHETIC, falkordb_up, load_company, synthetic_company, write_company
from pydantic import ValidationError

SLUG = "synthetic"
NOW = "2026-10-17T10:00:00Z"
KEEPER = "citadel_keeper"
ARCHIVIST = "citadel_archivist"
CTX = Ctx("agent:keeper", KEEPER, NOW)  # type: ignore[arg-type]
OLD = "Who decided the old pricing model?"  # nothing in the fake brain relates to it
DOC = "synthetic:doc:docs/old-auth-design.md"  # archived: "Old auth system design"


def clock() -> str:
    return NOW


def seed_gap(store, text: str = OLD, status: str = "open") -> str:
    [row] = store.write(
        "ledger/open_gap",
        "citadel_brain",
        {"uid": gap_uid(), "kind": "failed_question", "text": text, "norm": text.lower(),
         "now": "2026-10-17T09:00:00Z"},
    )  # fmt: skip
    if status != "open":
        move = {"uid": row["uid"], "from": ["open"], "to": status, "now": "2026-10-17T09:01:00Z"}
        assert store.write("ledger/set_gap_status", KEEPER, move)
    return row["uid"]


def get_gap(store, uid: str) -> Gap:
    [row] = store.read("ledger/get_gap", {"uid": uid})
    return Gap(**row)


def requests(store, gap: str) -> list[ArchiveRequest]:
    return [
        ArchiveRequest(**r) for r in store.read("ledger/archive_requests_for_gap", {"gap": gap})
    ]


def actions(store, gap: str | None = None) -> list[str]:
    return [e.action for e in store.log if gap is None or e.gap == gap]


def ask(gap: str, topic: str = "old pricing model") -> SubmitKeeperDecision:
    why = "Nobody could ground it; it is about older history."
    return SubmitKeeperDecision(gap=gap, outcome="ask_archivist", topic=topic, reason=why)


def open_request(store, *, gap: str | None, asked_by: str = "keeper", text: str = "old pricing",
                 now: str = NOW) -> str:  # fmt: skip
    params = {"uid": archive_uid(), "kind": "topic", "text": text, "asked_by": asked_by,
              "gap": gap, "norm": norm("topic", text, []), "now": now}  # fmt: skip
    [row] = store.write("ledger/archive_open_request", KEEPER, params)
    return row["uid"]


def waiting_gap(store, text: str = OLD, topic: str = "old pricing model") -> tuple[str, str]:
    """A gap the Keeper sent to the Archivist: (gap uid, its request's uid)."""
    gap = seed_gap(store, text, status="in_review")
    apply_decision(store, CTX, get_gap(store, gap), ask(gap, topic))
    [req] = requests(store, gap)
    return gap, req.uid


class FakeAnswer:
    """`answer_request` that ends each request with the given status, outcome and reason,
    records a find for `found`, and remembers what it was called with."""

    def __init__(self, status: str = "answered", outcome: str | None = "found",
                 reason: str | None = None):  # fmt: skip
        self.ending = (status, outcome, reason)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, store, slug, request, *, client, tier, **kw) -> ArchiveRequest:
        self.calls.append({"uid": request.uid, "tier": tier, "client": client, **kw})
        status, outcome, reason = self.ending
        store.write("ledger/archive_set_request", ARCHIVIST, {
            "uid": request.uid, "from": ["open"], "to": status, "reason": reason,
            "outcome": outcome if status == "answered" else None,
            "summary": f"{outcome or status} for {request.text}", "now": NOW})  # fmt: skip
        if outcome == "found":
            store.write("ledger/archive_write_find", ARCHIVIST, {
                "request": request.uid, "uid": "old:item:1", "title": "Old pricing decision",
                "date": "2024-01-02", "why": "It is the decision.", "verdict": "holds",
                "quote": "We decided to price per seat in 2024."})  # fmt: skip
        [row] = store.read("ledger/archive_get_request", {"uid": request.uid})
        return ArchiveRequest(**row)


@pytest.fixture
def answer(monkeypatch):
    fake = FakeAnswer()
    monkeypatch.setattr(review_module, "answer_request", fake)
    return fake


@pytest.fixture
def two_per_review(monkeypatch):
    monkeypatch.setenv("ARCHIVIST_PER_REVIEW", "2")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def run_review(store, brain=None, *, budget=5, trigger="manual", client_for=offline_client, **kw):
    brain = brain or FakeBrainFacts()
    return review(store, SLUG, budget=budget, trigger=trigger, client_for=client_for,
                  graph_run=fake_brain, brain=brain, now=clock, **kw)  # fmt: skip


# --- decide ------------------------------------------------------------------------------------


def test_decide_ask_archivist_moves_gap():
    store = MemoryKeeperStore(SLUG)
    gap = seed_gap(store, status="in_review")
    rows = apply_decision(store, CTX, get_gap(store, gap), ask(gap))
    [req] = requests(store, gap)
    assert rows == [{"uid": gap, "status": "waiting_archive", "request": req.uid}]
    g = get_gap(store, gap)
    assert (g.status, g.archive_asked, g.attempts) == ("waiting_archive", True, 0)
    assert (req.kind, req.text, req.asked_by, req.gap, req.status) == (
        "topic", "old pricing model", "keeper", gap, "open")  # fmt: skip
    assert req.norm == norm("topic", "old pricing model", [])
    assert actions(store, gap) == ["archive_requested"]


def test_second_ask_becomes_needs_person():
    store = MemoryKeeperStore(SLUG)
    gap = seed_gap(store, status="in_review")
    store.write("ledger/gap_archive_asked", KEEPER, {"uid": gap})
    rows = apply_decision(store, CTX, get_gap(store, gap), ask(gap))
    assert rows == [{"uid": gap, "status": "needs_person"}]
    g = get_gap(store, gap)
    assert (g.status, g.reason) == ("needs_person", "already asked the Archivist")
    assert requests(store, gap) == []
    assert actions(store, gap) == ["needs_person"]


def test_ask_for_a_question_already_in_flight_leaves_the_gap_in_review():
    """The same question is already open (Ask's, or another gap's): no second request; the gap
    stays in review, so the review releases it to `open` and the next round reads the answer."""
    store = MemoryKeeperStore(SLUG)
    other = open_request(store, gap=None, asked_by="ask", text="old pricing model")
    gap = seed_gap(store, status="in_review")
    rows = apply_decision(store, CTX, get_gap(store, gap), ask(gap))
    assert rows == [{"uid": gap, "status": "in_review", "request": other}]
    assert get_gap(store, gap).status == "in_review"
    assert requests(store, gap) == []
    assert get_gap(store, gap).archive_asked is True  # it asked: it ends, served or not
    [entry] = [e for e in store.log if e.gap == gap]
    assert entry.action == "archive_requested" and other in (entry.why or "")


def test_ask_on_a_gap_not_in_review_writes_nothing():
    store = MemoryKeeperStore(SLUG)
    gap = seed_gap(store)
    assert apply_decision(store, CTX, get_gap(store, gap), ask(gap)) == []
    assert requests(store, gap) == [] and store.log == []
    assert get_gap(store, gap).archive_asked is False


def test_ask_archivist_needs_a_topic():
    with pytest.raises(ValidationError):
        SubmitKeeperDecision(gap="gap:1", outcome="ask_archivist", reason="r")
    with pytest.raises(ValidationError):
        SubmitKeeperDecision(gap="gap:1", outcome="ask_archivist", topic="  ", reason="r")
    assert ask("gap:1").uids() == []


def ungrounded(role: str) -> dict[str, Any]:
    return {"role": role, "can_ground": False, "kind": None, "subject": None, "cites": []}


@pytest.mark.parametrize(
    ("text", "consults", "outcome", "topic"),
    [
        ("who decided the old auth system?", [ungrounded("pm"), ungrounded("qa")],
         "ask_archivist", "old auth system"),
        ("What is the history of billing?", [ungrounded("pm"), ungrounded("qa")],
         "ask_archivist", "history of billing"),
        ("Who holds the golden key?", [ungrounded("pm"), ungrounded("qa")],
         "needs_person", None),  # "old" only inside words
        ("who decided the old auth system?", [ungrounded("pm")], "needs_person", None),
    ],
)  # fmt: skip
def test_offline_keeper_asks_the_archivist_for_old_history(text, consults, outcome, topic):
    context = {"gap": {"uid": "gap:1", "text": text}, "consults": consults}
    out = keeper_policy.decide(context, Results())
    assert out["outcome"] == outcome
    assert out.get("topic") == topic


def test_keeper_prompt_names_ask_archivist():
    prompt = ROLES["keeper"].prompt
    assert "`ask_archivist`" in prompt and "older than" in prompt


# --- the review's archive step -----------------------------------------------------------------


def test_review_asks_and_runs_the_archivist_in_the_same_review(answer):
    """Consults cannot ground an old question: the Keeper asks, and the review runs the request
    (tier keeper, the archivist's client, the review's graph tools) after its decide step."""
    store = MemoryKeeperStore(SLUG)
    gap = seed_gap(store)
    r = run_review(store)
    [req] = requests(store, gap)
    [call] = answer.calls
    assert (call["uid"], call["tier"], call["graph_run"]) == (req.uid, "keeper", fake_brain)
    assert isinstance(call["client"], ScriptedClient)
    assert "should_stop" not in call  # a stop waits for the run, as for any job
    assert call["building"](SLUG) is False
    g = get_gap(store, gap)
    assert (g.status, g.attempts, g.archive_asked) == ("open", 0, True)
    assert (r.state, r.archive_reopened) == ("done", [gap])
    assert store.reviews[-1].archive_reopened == [gap]
    log = actions(store, gap)
    assert log.index("archive_requested") < log.index("archive_returned")
    [returned] = [e for e in store.log if e.action == "archive_returned"]
    assert returned.evidence == ["old:item:1"]


@pytest.mark.parametrize(
    ("status", "outcome", "reason", "why"),
    [
        ("answered", "nothing_found", None, "nothing_found"),
        ("answered", "nothing_found", "step_limit", "nothing_found: step_limit"),
        ("failed", None, "no_answer", "no_answer"),
        ("refused", None, "daily_cap", "daily_cap"),
    ],
)
def test_nothing_found_needs_person(monkeypatch, status, outcome, reason, why):
    monkeypatch.setattr(review_module, "answer_request", FakeAnswer(status, outcome, reason))
    store = MemoryKeeperStore(SLUG)
    gap, req = waiting_gap(store)
    r = run_review(store, budget=1)
    g = get_gap(store, gap)
    assert (g.status, g.reason, g.attempts) == ("needs_person", why, 0)
    assert r.archive_reopened == []
    [entry] = [e for e in store.log if e.gap == gap and e.action == "needs_person"]
    assert req in (entry.why or "")


def test_already_in_brain_reopens(monkeypatch):
    monkeypatch.setattr(review_module, "answer_request", FakeAnswer("answered", "already_in_brain"))
    store = MemoryKeeperStore(SLUG)
    gap, _ = waiting_gap(store)
    r = run_review(store, budget=1)
    assert get_gap(store, gap).status == "open"
    assert r.archive_reopened == [gap]
    assert "archive_returned" in actions(store, gap)


def test_archive_runs_keeper_requests_oldest_first_up_to_the_cap(answer, two_per_review):
    """Only open requests the Keeper asked; at most archivist_per_review, oldest first. A gap
    whose request did not run stays waiting_archive, and the next review runs it first."""
    store = MemoryKeeperStore(SLUG)
    gaps = []
    for i, when in enumerate(["2026-10-17T09:03:00Z", "2026-10-17T09:01:00Z",
                              "2026-10-17T09:02:00Z"]):  # fmt: skip
        gap = seed_gap(store, f"old question {i}", status="waiting_archive")
        open_request(store, gap=gap, text=f"old topic {i}", now=when)
        gaps.append(gap)
    ask_req = open_request(store, gap=None, asked_by="ask", text="old ask", now="2026-10-17T08:00Z")

    first = run_review(store, budget=1)
    assert [c["uid"] for c in answer.calls] == [requests(store, g)[0].uid for g in gaps[1:]]
    assert first.archive_reopened == [gaps[1], gaps[2]]
    assert get_gap(store, gaps[0]).status == "waiting_archive"  # not released, not decided
    assert store.read("ledger/archive_get_request", {"uid": ask_req})[0]["status"] == "open"

    second = run_review(store, budget=1)  # it also picks an open gap, which asks anew
    assert answer.calls[2]["uid"] == requests(store, gaps[0])[0].uid  # the leftover goes first
    assert second.archive_reopened[0] == gaps[0]


def test_budget_zero_runs_no_archivist(answer):
    store = MemoryKeeperStore(SLUG)
    gap, _ = waiting_gap(store)
    run_review(store, budget=0)
    assert answer.calls == []
    assert get_gap(store, gap).status == "waiting_archive"


def test_stop_between_archive_requests_leaves_the_gap_waiting(monkeypatch, two_per_review):
    store = MemoryKeeperStore(SLUG)
    one, _ = waiting_gap(store, "old one?", "old one")
    two, _ = waiting_gap(store, "old two?", "old two")
    stop = {"now": False}

    class StopAfterOne(FakeAnswer):
        def __call__(self, *a, **kw):
            stop["now"] = True
            return super().__call__(*a, **kw)

    fake = StopAfterOne()
    monkeypatch.setattr(review_module, "answer_request", fake)
    r = run_review(store, budget=1, should_stop=lambda: stop["now"])
    assert (r.state, r.stop) == ("stopped", "requested")
    assert len(fake.calls) == 1
    [reopened] = r.archive_reopened  # recorded though the run stopped
    assert reopened in (one, two) and store.reviews[-1].archive_reopened == [reopened]
    assert get_gap(store, two if reopened == one else one).status == "waiting_archive"


def test_brain_gone_before_a_request_stops_and_the_gap_waits(answer):
    store = MemoryKeeperStore(SLUG)
    gap, req = waiting_gap(store)

    class GoneAfterNoticing(FakeBrainFacts):
        def notice(self, slug: str, kind: str, limit: int) -> list[dict[str, Any]]:
            self.exists = False  # a rebuild began after the noticing step
            return super().notice(slug, kind, limit)

        def graph_exists(self, slug: str) -> bool:
            return self.exists

    r = run_review(store, GoneAfterNoticing(), budget=1)
    assert (r.state, r.stop) == ("stopped", "brain_unavailable")
    assert answer.calls == []
    assert get_gap(store, gap).status == "waiting_archive"
    assert store.read("ledger/archive_get_request", {"uid": req})[0]["status"] == "open"


def test_a_building_refusal_puts_the_request_back(monkeypatch):
    """The brain went away between the review's check and the Archivist's: the request is open
    again for the next review, the gap still waits, and the review stops brain_unavailable."""
    monkeypatch.setattr(review_module, "answer_request",
                        FakeAnswer("refused", None, "building"))  # fmt: skip
    store = MemoryKeeperStore(SLUG)
    gap, req = waiting_gap(store)
    r = run_review(store, budget=1)
    assert (r.state, r.stop) == ("stopped", "brain_unavailable")
    assert get_gap(store, gap).status == "waiting_archive"
    assert store.read("ledger/archive_get_request", {"uid": req})[0]["status"] == "open"


def test_a_request_left_running_is_run_again(answer):
    """A review killed during the Archivist left its request running: the next review puts it
    back to open, runs it and settles the gap. Ask's running requests are left alone."""
    store = MemoryKeeperStore(SLUG)
    gap, req = waiting_gap(store)
    move = {"uid": req, "from": ["open"], "to": "running", "now": NOW}
    store.write("ledger/archive_set_request", ARCHIVIST, move)
    asks = open_request(store, gap=None, asked_by="ask", text="old ask")
    store.write("ledger/archive_set_request", ARCHIVIST, {**move, "uid": asks})
    r = run_review(store, budget=1)
    assert [c["uid"] for c in answer.calls] == [req]
    assert r.archive_reopened == [gap] and get_gap(store, gap).status == "open"
    assert "archive_released" in actions(store, gap)
    assert store.read("ledger/archive_get_request", {"uid": asks})[0]["status"] == "running"


def test_release_orphans_leaves_waiting_archive(answer):
    store = MemoryKeeperStore(SLUG)
    gap, _ = waiting_gap(store)
    orphan = seed_gap(store, "What caused the rotation race?", status="in_review")
    run_review(store, budget=0)  # releases orphans; budget 0 runs no Archivist
    assert get_gap(store, orphan).status == "open"
    assert get_gap(store, gap).status == "waiting_archive"
    assert "gap_released" not in actions(store, gap)


def test_a_reopened_gap_is_consulted_again_with_the_finds(answer):
    """found -> open with no attempt used; the follow-on review posts a fresh consult round
    whose context lists the request's summary and finds, and the Keeper decides from it."""
    store = MemoryKeeperStore(SLUG)
    gap = seed_gap(store)
    run_review(store)
    seen: list[dict[str, Any]] = []

    def recording(role: str, job: str) -> ScriptedClient:
        policy = POLICIES[(role, job)]

        def play(context, results):
            if not results.calls:
                seen.append({"role": role, "job": job, **context})
            return policy(context, results)

        return ScriptedClient(play)

    r = run_review(store, budget=1, trigger="archive", client_for=recording)
    assert r.trigger == "archive" and store.reviews[-1].trigger == "archive"
    consults = [s for s in seen if s["job"] == "consult"]
    assert sorted(s["role"] for s in consults) == ["pm", "qa"]
    for s in consults:
        assert s["consult"]["uid"].endswith(":archive")
        [entry] = s["archive"]
        assert entry["summary"] == "found for old pricing model"
        assert entry["finds"] == [{"uid": "old:item:1", "title": "Old pricing decision",
                                   "date": "2024-01-02", "verdict": "holds"}]  # fmt: skip
    [decided] = [s for s in seen if s["job"] == "decide"]
    assert decided["archive"][0]["finds"][0]["uid"] == "old:item:1"
    # still ungrounded in the fake brain: the Keeper may not ask again
    g = get_gap(store, gap)
    assert (g.status, g.reason, g.attempts) == ("needs_person", "already asked the Archivist", 0)
    assert len(requests(store, gap)) == 1


def test_consult_context_lists_the_archive_only_when_answered():
    store = MemoryKeeperStore(SLUG)
    gap, req = waiting_gap(store)
    consult = Subject("consult", "c:1", {"uid": "c:1", "gap": gap, "role": "pm", "attempt": 0})
    ctx = Ctx("agent:pm", "citadel_pm", NOW)  # type: ignore[arg-type]
    job = ROLES["pm"].job("consult")
    assert "archive" not in job.context(store, ctx, consult)  # still open
    FakeAnswer()(store, SLUG, ArchiveRequest(**store.read("ledger/archive_get_request",
                                                          {"uid": req})[0]),
                 client=None, tier="keeper")  # fmt: skip
    [entry] = job.context(store, ctx, consult)["archive"]
    assert entry["finds"][0]["uid"] == "old:item:1"


# --- offline, on the synthetic company ---------------------------------------------------------


@pytest.fixture
def synthetic_slug(tmp_path, monkeypatch):
    """A throwaway company: the synthetic JSONL (with archive/) under a temp repo root, ingested
    into brain_<slug>; deleted afterwards."""
    if not falkordb_up():
        pytest.skip("FalkorDB not reachable (make up)")
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    folder = tmp_path / "synthetic"
    shutil.copytree(SYNTHETIC, folder, ignore=shutil.ignore_patterns("tickets", "*.py"))
    name = f"archtest_keeper_{uuid.uuid4().hex[:8]}"
    cfg = synthetic_company(name, folder=folder)
    write_company(cfg)
    db.delete_graph(name)
    load_company(cfg)
    yield name
    db.delete_graph(name)


def test_review_runs_archivist_and_reopens_gap(synthetic_slug):
    """pm and qa cannot ground "who decided the old auth system?"; the offline Keeper asks the
    Archivist, the review runs it (the real job, offline policy, the synthetic archive): it finds
    the old auth design, the gap goes back to open with no attempt used, and the follow-on
    review's consults are given the finds."""
    store = MemoryKeeperStore(synthetic_slug)
    gap = seed_gap(store, "who decided the old auth system?")

    def cannot_ground(context, results):
        return {"consult": context["consult"]["uid"], "can_ground": False, "cites": []}

    def first_round(role: str, job: str):
        return ScriptedClient(cannot_ground) if job == "consult" else offline_client(role, job)

    r = review(store, synthetic_slug, budget=1, trigger="manual", client_for=first_round,
               brain=keeper_decide.DEFAULT_BRAIN)  # fmt: skip
    assert r.state == "done", r.stop
    [req] = requests(store, gap)
    assert (req.asked_by, req.kind, req.text, req.status, req.outcome) == (
        "keeper", "topic", "old auth system", "answered", "found")  # fmt: skip
    finds = store.read("ledger/archive_finds", {"requests": [req.uid]})
    assert DOC in [f["uid"] for f in finds]
    g = get_gap(store, gap)
    assert (g.status, g.attempts, g.archive_asked) == ("open", 0, True)
    assert r.archive_reopened == [gap]
    steps = store.read("ledger/review_steps", {"reviews": [req.uid]})
    assert steps and {s["actor"] for s in steps} == {"archivist"}  # under the request's uid

    seen: list[dict[str, Any]] = []

    def recording(role: str, job: str) -> ScriptedClient:
        policy = POLICIES[(role, job)]

        def play(context, results):
            if job == "consult" and not results.calls:
                seen.append(context)
            return policy(context, results)

        return ScriptedClient(play)

    after = review(store, synthetic_slug, budget=1, trigger="archive", client_for=recording,
                   brain=keeper_decide.DEFAULT_BRAIN)  # fmt: skip
    assert after.state == "done", after.stop
    assert len(seen) == 2
    for context in seen:
        assert context["gap"]["uid"] == gap
        assert DOC in [f["uid"] for f in context["archive"][0]["finds"]]
