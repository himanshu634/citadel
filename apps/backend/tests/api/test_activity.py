"""Agent activity route: Ask turns as runs with their steps on the graph (memory history)."""

from __future__ import annotations

import pytest
from agents.testing import FakeClient, reply, submit, text, tool_use

from .conftest import write
from .test_ask import make_client
from .test_threads import ask


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
