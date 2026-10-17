"""Agent activity route: Ask turns as runs with their steps on the graph (memory history)."""

from __future__ import annotations

import pytest
from agents.keeper.model import gap_uid
from agents.policies import offline_client
from agents.testing import TOOLSET, FakeClient, fake_brain, reply, submit, text, tool_use
from backend.api import create_app
from backend.api.ask import Asker
from backend.keeper_runs import KeeperRuns
from fastapi.testclient import TestClient

from .conftest import write
from .test_ask import make_client
from .test_keeper_api import GatedBrain
from .test_threads import ask

KEEPER = "citadel_keeper"


@pytest.fixture
def company(api_root):
    write(api_root, "synthetic", name="Synthetic Co")
    return "synthetic"


def test_an_ask_turn_is_a_run_with_its_touched_nodes(company, runner):
    claude = FakeClient(
        reply(text("Let me look."), tool_use("t1", "related_work_items", {"text": "jwt"})),
        reply(submit("t2", "JWT [1].", ["pr:1"])),
    )
    client = make_client(runner, claude)
    thread_id = ask(client, company, "Why JWT?")["start"]["thread_id"]

    got = client.get(f"/api/companies/{company}/activity").json()
    assert got["running"] is False
    [run] = got["runs"]
    assert (run["id"], run["source"], run["actor"], run["title"], run["status"]) == (
        f"ask:{thread_id}:1", "ask", "brain", "Why JWT?", "done")  # fmt: skip
    assert run["thread_id"] == thread_id
    tools = [(s["n"], s["tool"], s["kind"], s["actor"]) for s in run["steps"]]
    assert tools == [
        (1, "related_work_items", "graph", "brain"),
        (2, "submit_answer", "submit", "brain"),
    ]
    first = run["steps"][0]
    assert first["input"] == {"text": "jwt"} and "pr:1" in first["touched"]
    assert len(first["touched"]) == len(set(first["touched"]))


def test_runs_are_newest_first_and_limited(company, runner):
    client = make_client(runner, FakeClient(*[reply(submit(f"t{i}", "x", [])) for i in range(3)]))
    for i in range(3):
        ask(client, company, f"Q{i}?")
    got = client.get(f"/api/companies/{company}/activity", params={"limit": 2}).json()
    assert [r["title"] for r in got["runs"]] == ["Q2?", "Q1?"]


def test_a_turn_no_run_can_finish_shows_as_stopped(company, runner, history):
    history.write("start_turn", {"thread_id": "gone", "title": "Q?", "question": "Q?", "at": 1})
    client = make_client(runner, FakeClient())
    got = client.get(f"/api/companies/{company}/activity").json()
    assert [r["status"] for r in got["runs"]] == ["stopped"] and got["running"] is False


def test_no_chats_is_an_empty_list(company, runner):
    got = make_client(runner, FakeClient()).get(f"/api/companies/{company}/activity").json()
    assert got == {"runs": [], "running": False}


def test_unknown_company_404(runner):
    assert make_client(runner, FakeClient()).get("/api/companies/nope/activity").status_code == 404


# --- Keeper reviews ---------------------------------------------------------------------------


@pytest.fixture
def brain():
    b = GatedBrain()
    b.gate.set()
    yield b
    b.gate.set()  # never leave a review blocked


@pytest.fixture
def keeper(ledger, brain):
    """Reviews on the in-memory ledger with the scripted jobs and the fake brain (offline)."""
    return KeeperRuns(store_for=lambda slug: ledger, client_for=offline_client,
                      has_key=lambda: True, brain=brain, graph_run=fake_brain)  # fmt: skip


def both_client(runner, keeper, claude) -> TestClient:
    asker = Asker(client=lambda: claude, toolset=lambda: TOOLSET, checkpointer=lambda slug: None,
                  graph_exists=lambda slug: True)  # fmt: skip
    return TestClient(create_app(runner, asker, keeper=keeper))


def seed_review(ledger, uid, at, state="done", steps=()):
    ledger.write("ledger/review_start", KEEPER, {"uid": uid, "trigger": "build", "budget": 3,
                                                 "now": at})  # fmt: skip
    for n, (actor, tool) in enumerate(steps, start=1):
        ledger.write("ledger/write_step", KEEPER, {"review": uid, "n": n, "actor": actor,
                     "tool": tool, "input": {"system": "Auth"}, "status": "done", "count": 1,
                     "touched": ["system:Auth"], "at": at})  # fmt: skip
    if state != "running":
        ledger.write("ledger/review_finish", KEEPER, {"uid": uid, "state": state, "now": at})


def test_keeper_reviews_are_runs_next_to_ask_turns(company, runner, keeper, ledger):
    seed_review(ledger, "review:old", "2020-01-01T00:00:00Z", steps=[("pm", "work_history")])
    seed_review(ledger, "review:skip", "2020-01-02T00:00:00Z", state="skipped")  # left out
    client = both_client(runner, keeper, FakeClient(reply(submit("t1", "x", []))))
    thread_id = ask(client, company, "Why JWT?")["start"]["thread_id"]
    seed_review(ledger, "review:lost", "2100-01-01T00:00:00Z", state="running")  # no live run

    got = client.get(f"/api/companies/{company}/activity").json()
    assert [(r["id"], r["status"]) for r in got["runs"]] == [
        ("keeper:review:lost", "stopped"), (f"ask:{thread_id}:1", "done"),
        ("keeper:review:old", "done")]  # fmt: skip
    assert got["running"] is False
    old = got["runs"][2]
    assert (old["source"], old["actor"], old["title"]) == (
        "keeper", "keeper", "Keeper review after a build")  # fmt: skip
    assert [(s["n"], s["actor"], s["tool"], s["touched"]) for s in old["steps"]] == [
        (1, "pm", "work_history", ["system:Auth"])]  # fmt: skip
    limited = client.get(f"/api/companies/{company}/activity", params={"limit": 2}).json()
    assert [r["id"] for r in limited["runs"]] == ["keeper:review:lost", f"ask:{thread_id}:1"]


def test_a_running_review_keeps_the_page_watching(company, runner, keeper, ledger, brain):
    [gap] = ledger.write("ledger/open_gap", "citadel_brain", {
        "uid": gap_uid(), "kind": "failed_question", "text": "What caused the rotation race?",
        "norm": "what caused the rotation race?", "now": "2026-10-17T09:00:00Z"})  # fmt: skip
    client = both_client(runner, keeper, FakeClient())
    brain.gate.clear()  # the review waits at its first look at the brain
    assert client.post(f"/api/companies/{company}/keeper/review").status_code == 202

    got = client.get(f"/api/companies/{company}/activity").json()
    [run] = got["runs"]
    assert (run["source"], run["status"], got["running"]) == ("keeper", "running", True)
    assert run["title"] == "Keeper review on request"  # nothing picked yet

    brain.gate.set()
    assert keeper.wait(company, 5)
    got = client.get(f"/api/companies/{company}/activity").json()
    [run] = got["runs"]
    assert (run["status"], got["running"]) == ("done", False)
    assert run["title"] == "What caused the rotation race?"
    assert {s["actor"] for s in run["steps"]} == {"pm", "qa", "keeper"}
    assert all(s["status"] == "done" for s in run["steps"]) and gap["created"]


def test_skipped_reviews_do_not_crowd_out_older_ones(company, runner, keeper, ledger):
    seed_review(ledger, "review:real", "2020-01-01T00:00:00Z", steps=[("qa", "work_history")])
    for i in range(10):
        seed_review(ledger, f"review:skip{i}", f"2020-01-{i + 2:02d}T00:00:00Z", state="skipped")
    client = both_client(runner, keeper, FakeClient())
    got = client.get(f"/api/companies/{company}/activity", params={"limit": 2}).json()
    assert [r["id"] for r in got["runs"]] == ["keeper:review:real"]
