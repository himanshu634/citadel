"""The Ask page's view of a run: agents.ask.ask_events with a scripted Claude (no API calls)."""

from __future__ import annotations

import threading

from agents import ask as agent
from agents.testing import TOOLSET, FakeClient, reply, settings, submit, tool_use  # noqa: F401
from langgraph.checkpoint.memory import InMemorySaver


def events(client, question="Why JWT?", thread_id=None, **kw):
    return list(
        agent.ask_events("synthetic", question, thread_id, client=client, toolset=TOOLSET, **kw)
    )


def test_events_come_in_order_and_number_the_graph_steps():
    client = FakeClient(
        reply(
            tool_use("t1", "related_work_items", {"text": "jwt"}),
            tool_use("t2", "related_work_items", {"text": "load", "limit": 1}),
        ),
        reply(submit("t3", "Sessions moved to JWT [1].", ["pr:1"])),
    )
    out = events(client)
    kinds = [e["kind"] for e in out]
    assert kinds == ["start", "step", "step", "step_done", "step_done", "step", "step_done",
                     "answer"]  # fmt: skip
    steps = [e for e in out if e["kind"] == "step_done"]
    assert [(s["tool"], s["n"]) for s in steps] == [
        ("related_work_items", 1),
        ("related_work_items", 2),
        ("submit_answer", None),
    ]
    first = steps[0]
    assert first["count"] == 2 and first["error"] is None and first["ms"] >= 0
    assert {n["uid"] for n in first["nodes"]} == {"pr:1", "issue:11"}
    assert first["rows"][0]["uid"] == "pr:1"
    answer = out[-1]
    assert answer["text"] == "Sessions moved to JWT [1]."
    assert answer["sources"][0]["uid"] == "pr:1"
    assert answer["sources"][0]["step"] == 1  # the step that first returned it
    assert answer["sources"][0]["label"] == "WorkItem"  # filled from the step's subgraph
    assert out[0]["thread_id"] == answer["thread_id"]


def test_a_rejected_answer_shows_as_a_failed_check():
    client = FakeClient(
        reply(tool_use("t1", "related_work_items", {"text": "jwt"})),
        reply(submit("t2", "Made up [1].", ["pr:999"])),
        reply(submit("t3", "Real [1].", ["pr:1"])),
    )
    checks = [e for e in events(client) if e["kind"] == "step_done" and e["n"] is None]
    assert "pr:999" in checks[0]["error"]
    assert checks[1]["error"] is None


def test_a_failing_query_is_a_step_with_an_error():
    client = FakeClient(
        reply(tool_use("t1", "related_work_items", {"text": "boom"})),
        reply(submit("t2", "Nothing found.", [])),
    )
    step = next(e for e in events(client) if e["kind"] == "step_done")
    assert step["error"] == "related_work_items failed: RuntimeError: query failed"
    assert step["nodes"] == [] and step["count"] == 0


def test_stop_ends_the_run_and_leaves_the_thread_valid():
    saver = InMemorySaver()
    stop = threading.Event()
    # The stopped run never ran its tool, so the follow-up has nothing to cite.
    client = FakeClient(
        reply(tool_use("t1", "related_work_items", {"text": "jwt"})),
        reply(submit("t9", "Not looked up yet.", [])),
    )
    run = agent.ask_events(
        "synthetic", "Why JWT?", client=client, toolset=TOOLSET, checkpointer=saver, stop=stop
    )
    seen = []
    for event in run:
        seen.append(event)
        if event["kind"] == "step":
            stop.set()  # the browser pressed Stop while the first tool was asked for
    answer = seen[-1]
    assert answer["kind"] == "answer" and answer["stop"] == "stopped" and answer["text"] is None

    second = agent.ask(
        "synthetic", "Try again", answer["thread_id"], client=client, toolset=TOOLSET,
        checkpointer=saver,
    )  # fmt: skip
    assert second.text == "Not looked up yet."
    blocks = [b for m in client.requests[-1]["messages"] for b in m["content"]]
    assert [b["type"] for b in blocks][:3] == ["text", "tool_use", "tool_result"]
    calls = [b["id"] for b in blocks if b["type"] == "tool_use"]
    answered = [b["tool_use_id"] for b in blocks if b["type"] == "tool_result"]
    assert calls == answered  # every tool call has its result


def test_step_limit_ends_every_asked_step_then_answers(monkeypatch):
    monkeypatch.setattr(agent, "RECURSION_LIMIT", 4)
    turns = [reply(tool_use(f"t{i}", "related_work_items", {"text": "jwt"})) for i in range(3)]
    out = events(FakeClient(*turns), checkpointer=InMemorySaver())
    assert out[-1]["kind"] == "answer" and out[-1]["stop"] == "step_limit"
    asked = {e["id"] for e in out if e["kind"] == "step"}
    done = {e["id"]: e for e in out if e["kind"] == "step_done"}
    assert asked == set(done)  # no step is left spinning on the page
    assert done["t1"]["error"] == "Not run: the step limit was reached." and done["t1"]["n"] == 2


def test_a_thread_left_broken_is_repaired_before_the_next_run():
    saver = InMemorySaver()
    client = FakeClient(
        reply(tool_use("t1", "related_work_items", {"text": "jwt"})),
        reply(submit("t2", "Fine.", [])),
    )
    graph = agent.build_graph(client, TOOLSET, saver)
    config = {"configurable": {"thread_id": "broken"}}
    graph.update_state(  # a run that died after Claude asked for a tool
        config,
        {"messages": [{"role": "user", "content": [{"type": "text", "text": "q"}]},
                      {"role": "assistant", "content": [{"type": "tool_use", "id": "dead",
                       "name": "related_work_items", "input": {"text": "x"}}]}]},
        as_node="call_claude",
    )  # fmt: skip
    client.replies.pop(0)  # the dead run used the first reply
    answer = agent.ask("synthetic", "Again", "broken", client=client, toolset=TOOLSET,
                       checkpointer=saver)  # fmt: skip
    assert answer.text == "Fine."
    blocks = [b for m in client.requests[-1]["messages"] for b in m["content"]]
    results = [b for b in blocks if b["type"] == "tool_result"]
    assert results[0]["tool_use_id"] == "dead" and "previous answer ended" in results[0]["content"]
