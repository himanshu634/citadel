"""The Keeper's routes: gaps, claims, approve/reject, the log, follow-ups, and review runs
started on demand, after an approval and after a build. Everything runs offline: an in-memory
ledger (the conftest's `ledger`), the scripted policies, the fake brain tools and FakeBrainFacts.
Nothing here touches FalkorDB or the API."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field

import pytest
from agents.keeper.model import gap_uid
from agents.policies import offline_client
from agents.testing import FakeBrainFacts, fake_brain
from backend.api import create_app
from backend.keeper_runs import KeeperRuns, ReviewNotStarted
from fastapi.testclient import TestClient

from .conftest import write
from .test_ask import frames
from .test_builds import wait_done

SLUG = "synthetic"
KEEPER = "citadel_keeper"
GROUNDED = "What caused the rotation race?"  # the fake brain relates one item: fake:pr:2
BASE = f"/api/companies/{SLUG}/keeper"


@dataclass
class GatedBrain(FakeBrainFacts):
    """FakeBrainFacts whose `graph_exists` waits for `gate`, so a review stays running."""

    gate: threading.Event = field(default_factory=threading.Event)

    def graph_exists(self, slug: str) -> bool:
        assert self.gate.wait(5), "test never opened the gate"
        return super().graph_exists(slug)


@pytest.fixture
def company(api_root):
    write(api_root, SLUG, name="Synthetic Co")
    return SLUG


@pytest.fixture
def brain():
    b = GatedBrain()
    b.gate.set()
    yield b
    b.gate.set()  # never leave a review blocked


@pytest.fixture
def keeper(ledger, brain):
    return KeeperRuns(
        store_for=lambda slug: ledger,
        client_for=offline_client,
        has_key=lambda: True,
        brain=brain,
        graph_run=fake_brain,
    )


@pytest.fixture
def kclient(runner, keeper):
    return TestClient(create_app(runner, keeper=keeper))


def seed_gap(store, text: str = GROUNDED, status: str = "open") -> str:
    [row] = store.write(
        "ledger/open_gap",
        "citadel_brain",
        {"uid": gap_uid(), "kind": "failed_question", "text": text, "norm": text.lower(),
         "now": "2026-10-17T09:00:00Z"},
    )  # fmt: skip
    if status != "open":
        store.write("ledger/set_gap_status", KEEPER, {"uid": row["uid"], "from": ["open"],
                    "to": status, "now": "2026-10-17T09:01:00Z"})  # fmt: skip
    return row["uid"]


def seed_claim(store, gap: str | None = None, status: str = "pending_approval") -> str:
    uid = f"claim:{len(store.claims):012d}"
    store.write(
        "ledger/write_claim",
        KEEPER,
        {"uid": uid, "kind": "owner", "subject": "system:Auth", "statement": "Alice owns Auth.",
         "value": "person:alice", "about": ["system:Auth"], "evidence": ["fake:pr:2"],
         "status": status, "critical": True, "author": "keeper", "gap": gap,
         "now": "2026-10-17T09:30:00Z"},
    )  # fmt: skip
    return uid


def wait_review(store, n: int = 1, timeout: float = 5):
    """The n-th review of the ledger, once it has ended."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(store.reviews) >= n and store.reviews[n - 1].state != "running":
            return store.reviews[n - 1]
        time.sleep(0.01)
    raise AssertionError(f"review {n} did not end: {store.reviews}")


# --- review runs ------------------------------------------------------------------------------


def test_review_route_runs_and_streams(kclient, company, ledger, brain):
    seed_gap(ledger)
    brain.gate.clear()  # the review waits at its first look at the brain
    r = kclient.post(f"{BASE}/review")
    assert r.status_code == 202
    assert (r.json()["state"], r.json()["trigger"]) == ("running", "manual")
    again = kclient.post(f"{BASE}/review")  # one review per company: the running one
    assert again.status_code == 202 and again.json()["uid"] == r.json()["uid"]
    brain.gate.set()  # the test client reads a stream whole: let the run end first
    got = frames(kclient.get(f"{BASE}/review/events").text)
    assert got[0][0] == "snapshot" and got[0][1]["uid"] == r.json()["uid"]
    kinds = [data["kind"] for name, data in got[1:] if name == "review"]
    assert kinds[0] == "start" and kinds[-1] == "done"
    assert any(data.get("claim") for _, data in got[1:])
    review = wait_review(ledger)
    assert (review.state, review.uid) == ("done", r.json()["uid"])
    log = [e["action"] for e in kclient.get(f"{BASE}/log").json()]
    assert log[0] == "review_done" and log[-1] == "review_start"
    assert "claim_written" in log


def test_subscribe_replays_then_follows_the_run_live(keeper, company, ledger, brain):
    seed_gap(ledger)
    brain.gate.clear()
    keeper.start(SLUG, "manual", 5)

    async def follow() -> list[str]:
        events = keeper.subscribe(SLUG)  # the run is still waiting at the gate
        try:
            brain.gate.set()
            return [e.kind async for e in events]
        finally:
            await events.aclose()

    kinds = asyncio.run(follow())
    assert kinds[0] == "start" and kinds[-1] == "done" and "step" in kinds
    assert keeper.wait(SLUG, 5) and not keeper.running(SLUG)
    assert keeper._subscribers == set()


def test_review_without_api_key_is_skipped(runner, ledger, brain, company):
    keeper = KeeperRuns(store_for=lambda slug: ledger, client_for=_no_client,
                        has_key=lambda: False, brain=brain, graph_run=fake_brain)  # fmt: skip
    client = TestClient(create_app(runner, keeper=keeper))
    assert client.post(f"{BASE}/review").status_code == 202
    review = wait_review(ledger)
    assert (review.state, review.stop) == ("skipped", "no_api_key")
    got = frames(client.get(f"{BASE}/review/events").text)
    assert got[-1][1]["kind"] == "skipped"


def _no_client(role, job):
    raise AssertionError("no LLM job may run without an API key")


def test_stop_review(kclient, company, ledger, brain):
    seed_gap(ledger)
    assert kclient.post(f"{BASE}/review/stop").status_code == 404  # nothing running
    brain.gate.clear()
    kclient.post(f"{BASE}/review")
    r = kclient.post(f"{BASE}/review/stop")
    assert r.status_code == 202 and r.json()["state"] == "running"
    brain.gate.set()
    review = wait_review(ledger)
    assert (review.state, review.stop) == ("stopped", "requested")


def test_events_without_any_review_is_404(kclient, company):
    assert kclient.get(f"{BASE}/review/events").status_code == 404


def test_startup_stops_a_review_cut_off_by_a_restart(runner, keeper, ledger, company):
    old = {"uid": "review:old", "trigger": "build", "budget": 3, "now": "2026-10-17T08:00:00Z"}
    ledger.write("ledger/review_start", KEEPER, old)
    with TestClient(create_app(runner, keeper=keeper)):
        pass
    [r] = ledger.reviews
    assert (r.state, r.stop) == ("stopped", "restart")


def test_build_done_starts_a_review(client, company, ledger, runner, gate):
    """The app's default Keeper (the conftest makes it offline, no API key) reviews after a
    build that finished."""
    client.post(f"/api/companies/{company}/builds", json={})
    gate.set()
    assert wait_done(runner, company).state == "done"
    review = wait_review(ledger)
    assert (review.trigger, review.budget, review.state) == ("build", 3, "skipped")


# --- claims -----------------------------------------------------------------------------------


def test_approve_twice_409(kclient, company, ledger, brain):
    gap = seed_gap(ledger, status="in_review")
    uid = seed_claim(ledger, gap)
    r = kclient.post(f"{BASE}/claims/{uid}/approve", json={"by": "Dana", "why": "Checked."})
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["approved_by"]) == ("accepted", "Dana")
    again = kclient.post(f"{BASE}/claims/{uid}/approve", json={"by": "Eve"})
    assert again.status_code == 409
    assert kclient.post(f"{BASE}/claims/{uid}/reject", json={"by": "Eve"}).status_code == 409
    # the approval starts a budget-0 review, so pm's follow-up shows
    review = wait_review(ledger)
    assert (review.trigger, review.budget, review.state) == ("approval", 0, "done")
    [f] = kclient.get(f"{BASE}/followups").json()
    assert f["claim"] == uid


def test_approve_unknown_claim_404(kclient, company):
    r = kclient.post(f"{BASE}/claims/claim:nope/approve", json={"by": "Dana"})
    assert r.status_code == 404
    r = kclient.post(f"{BASE}/claims/claim:nope/reject", json={"by": "Dana"})
    assert r.status_code == 404


def test_approve_with_the_brain_gone_is_503(kclient, company, ledger, brain):
    uid = seed_claim(ledger, seed_gap(ledger, status="in_review"))
    brain.exists = False
    r = kclient.post(f"{BASE}/claims/{uid}/approve", json={"by": "Dana"})
    assert r.status_code == 503 and SLUG in r.json()["detail"]
    assert ledger.claims[uid].status == "pending_approval"


def test_approval_body_is_checked(kclient, company, ledger):
    uid = seed_claim(ledger)
    assert kclient.post(f"{BASE}/claims/{uid}/approve", json={"by": ""}).status_code == 422
    long = {"by": "Dana", "why": "x" * 501}
    assert kclient.post(f"{BASE}/claims/{uid}/approve", json=long).status_code == 422


def test_reject_reopens_gap(kclient, company, ledger):
    gap = seed_gap(ledger, status="in_review")
    uid = seed_claim(ledger, gap)
    r = kclient.post(f"{BASE}/claims/{uid}/reject", json={"by": "Dana", "why": "Alice left."})
    assert r.status_code == 200
    assert (r.json()["status"], r.json()["why"]) == ("rejected", "Alice left.")
    [g] = kclient.get(f"{BASE}/gaps", params={"status": "open"}).json()
    assert (g["uid"], g["attempts"]) == (gap, 1)
    assert ledger.reviews == []  # a rejection starts no review
    [e] = kclient.get(f"{BASE}/log", params={"limit": 1}).json()
    assert (e["action"], e["actor"], e["claim"]) == ("claim_rejected", "Dana", uid)


# --- lists ------------------------------------------------------------------------------------


def test_lists_filter_by_status(kclient, company, ledger):
    open_gap = seed_gap(ledger, "Who owns billing?")
    seed_gap(ledger, "Who owns web?", status="in_review")
    pending = seed_claim(ledger)
    seed_claim(ledger, status="accepted")
    assert len(kclient.get(f"{BASE}/gaps").json()) == 2
    assert [g["uid"] for g in kclient.get(f"{BASE}/gaps?status=open").json()] == [open_gap]
    claims = kclient.get(f"{BASE}/claims?status=pending_approval").json()
    assert [c["uid"] for c in claims] == [pending]
    assert len(kclient.get(f"{BASE}/claims").json()) == 2
    assert kclient.get(f"{BASE}/gaps?status=nope").status_code == 422
    assert kclient.get(f"{BASE}/followups").json() == []


def test_unknown_company_404(kclient, company):
    for method, path in [
        ("GET", "gaps"),
        ("GET", "claims"),
        ("GET", "log"),
        ("GET", "followups"),
        ("POST", "review"),
        ("POST", "review/stop"),
        ("GET", "review/events"),
    ]:
        r = kclient.request(method, f"/api/companies/nope/keeper/{path}")
        assert r.status_code == 404, (method, path)
    r = kclient.post("/api/companies/nope/keeper/claims/claim:x/approve", json={"by": "Dana"})
    assert r.status_code == 404


def test_default_seams_are_fixed_when_the_app_is_made(runner, ledger, company, monkeypatch):
    """A review thread can outlive a test's patches (a build released at teardown): the app's
    Keeper keeps the seams it was made with, so it never reaches a real keeper_<slug> or Claude."""
    app = create_app(runner)

    def real_store(slug):
        raise AssertionError("the store was looked up after the app was made")

    monkeypatch.setattr("backend.keeper_runs.keeper_store", real_store)
    monkeypatch.setattr("backend.keeper_runs.has_api_key", lambda: True)
    app.state.keeper.start(SLUG, "manual", 0)
    assert app.state.keeper.wait(SLUG, 5)
    [review] = ledger.reviews
    assert review.state == "skipped"


class SlowStart:
    """The ledger, except that `ledger/review_start` waits for `gate`: a review that has not
    recorded itself yet."""

    def __init__(self, store, gate: threading.Event):
        self._store, self._gate = store, gate

    def write(self, name, db_user, params):
        if name == "ledger/review_start":
            assert self._gate.wait(5), "test never opened the gate"
        return self._store.write(name, db_user, params)

    def __getattr__(self, name):
        return getattr(self._store, name)


@pytest.fixture
def slow_gate():
    g = threading.Event()
    yield g
    g.set()


def test_start_never_returns_an_older_review_as_the_new_one(ledger, brain, slow_gate):
    old = {"uid": "review:old", "trigger": "build", "budget": 3, "now": "2026-10-17T08:00:00Z"}
    ledger.write("ledger/review_start", KEEPER, old)
    ledger.write("ledger/review_finish", KEEPER, {"uid": "review:old", "state": "done",
                                                  "now": "2026-10-17T08:01:00Z"})  # fmt: skip
    slow = SlowStart(ledger, slow_gate)
    runs = KeeperRuns(store_for=lambda slug: slow, client_for=offline_client,
                      has_key=lambda: True, brain=brain, graph_run=fake_brain,
                      start_wait=0.05)  # fmt: skip
    with pytest.raises(ReviewNotStarted):
        runs.start(SLUG, "manual", 0)
    slow_gate.set()
    assert runs.wait(SLUG, 5)
    assert [r.uid == "review:old" for r in ledger.reviews] == [True, False]


def test_approve_does_not_wait_for_its_review(runner, ledger, brain, company, slow_gate):
    slow = SlowStart(ledger, slow_gate)
    runs = KeeperRuns(store_for=lambda slug: slow, client_for=offline_client,
                      has_key=lambda: True, brain=brain, graph_run=fake_brain)  # fmt: skip
    client = TestClient(create_app(runner, keeper=runs))
    uid = seed_claim(ledger, seed_gap(ledger, status="in_review"))
    began = time.monotonic()
    r = client.post(f"{BASE}/claims/{uid}/approve", json={"by": "Dana"})
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert time.monotonic() - began < 1  # start_wait is 10 s: approve did not wait for it
    slow_gate.set()
    assert wait_review(ledger).trigger == "approval"


def test_blank_names_are_refused_and_text_is_stripped(kclient, company, ledger):
    uid = seed_claim(ledger, seed_gap(ledger, status="in_review"))
    blank = kclient.post(f"{BASE}/claims/{uid}/reject", json={"by": "   "})
    assert blank.status_code == 422
    r = kclient.post(f"{BASE}/claims/{uid}/reject", json={"by": "  Dana ", "why": " Gone. "})
    assert r.status_code == 200
    assert (r.json()["approved_by"], r.json()["why"]) == ("Dana", "Gone.")
