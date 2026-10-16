"""Backfill: a thread's checkpoint replayed into the history (scripted Claude, memory store)."""

from __future__ import annotations

from datetime import UTC, datetime

from brain.agents import ask as agent
from brain.agents.backfill import replay
from brain.agents.history import MemoryChatStore, Recorder
from brain.agents.traces import Trace
from langgraph.checkpoint.memory import InMemorySaver
from tests.test_agent import TOOLSET, FakeClient, reply, settings, submit, text, tool_use  # noqa: F401
from tests.test_history import record


def checkpoint(saver, thread_id):
    return saver.get_tuple({"configurable": {"thread_id": thread_id}}).checkpoint["channel_values"]


def write(store, turns):
    for t in turns:
        rec = Recorder(store, t.question, clock=lambda at=t.at: at)
        for e in t.events:
            rec.on(e)
        rec.answer(t.answer, t.model, ms=t.ms)


def two_turns(saver):
    first = agent.ask(
        "synthetic", "Why JWT?",
        client=FakeClient(
            reply(text("Looking."), tool_use("t1", "related_work_items", {"text": "jwt"})),
            reply(submit("t2", "Made up [1].", ["pr:999"])),
            reply(submit("t3", "JWT [1].", ["pr:1"])),
        ),
        toolset=TOOLSET, checkpointer=saver,
    )  # fmt: skip
    agent.ask("synthetic", "Sure?", first.thread_id,
              client=FakeClient(reply(submit("t4", "Yes [1].", ["pr:1"]))),
              toolset=TOOLSET, checkpointer=saver)  # fmt: skip
    return first.thread_id


def test_a_checkpoint_replays_into_the_same_history_a_live_run_writes():
    saver = InMemorySaver()
    thread_id = two_turns(saver)
    turns = replay(thread_id, checkpoint(saver, thread_id), 1_000, [])
    assert [t.question for t in turns] == ["Why JWT?", "Sure?"]

    store = MemoryChatStore()
    write(store, turns)
    one, two = store.get_thread(thread_id).turns
    assert (one.status, one.answer["text"], one.answer["sources"][0]["title"]) == (
        "done", "JWT [1].", "Switch sessions to JWT")  # fmt: skip
    assert one.answer["sources"][0]["step"] == 1
    assert [c.text for c in one.calls] == ["Looking.", None, None]
    assert [c.usage.input for c in one.calls] == [100, 100, 100]
    assert [(s.kind, s.n, s.status, s.call) for s in one.steps] == [
        ("graph", 1, "done", 1),
        ("submit", None, "failed", 2),
        ("submit", None, "done", 3),
    ]
    assert one.steps[0].count == 2 and one.steps[0].nodes  # from the trace channel
    assert two.answer["text"] == "Yes [1]." and store.threads[thread_id]["turns"] == 2


def test_the_live_and_the_backfilled_history_agree():
    saver, live = InMemorySaver(), MemoryChatStore()
    client = FakeClient(
        reply(text("Looking."), tool_use("t1", "related_work_items", {"text": "jwt"})),
        reply(submit("t2", "JWT [1].", ["pr:1"])),
    )
    answer = record(live, "Why JWT?", client, saver=saver)
    back = MemoryChatStore()
    write(back, replay(answer.thread_id, checkpoint(saver, answer.thread_id), 1_000, []))
    a, b = live.get_thread(answer.thread_id).turns[0], back.get_thread(answer.thread_id).turns[0]
    keep = {"id", "call", "n", "tool", "kind", "status", "count", "error", "nodes", "rels"}
    assert [s.model_dump(include=keep) for s in a.steps] == [
        s.model_dump(include=keep) for s in b.steps
    ]
    assert [c.text for c in a.calls] == [c.text for c in b.calls]
    assert {k: a.answer[k] for k in ("text", "sources", "path")} == {
        k: b.answer[k] for k in ("text", "sources", "path")
    }


def test_a_trace_line_dates_the_turn_and_carries_its_id():
    saver = InMemorySaver()
    thread_id = two_turns(saver)
    at = datetime(2026, 10, 16, 10, 0, tzinfo=UTC)
    line = Trace(id="tr1", at=at, slug="synthetic", via="api", thread_id=thread_id,
                 question="Sure?", ms=1500, model="claude-haiku-5-5", stop="stopped")  # fmt: skip
    one, two = replay(thread_id, checkpoint(saver, thread_id), 5_000, [line])
    assert one.at == 5_000 and one.trace_id is None  # no line: the checkpoint's time
    assert (two.at, two.ms, two.trace_id) == (int(at.timestamp() * 1000), 1500, "tr1")
    store = MemoryChatStore()
    write(store, [one, two])
    assert store.get_thread(thread_id).turns[1].status == "stopped"


def test_old_runs_without_a_trace_channel_rebuild_their_steps_from_the_results():
    saver = InMemorySaver()
    thread_id = two_turns(saver)
    values = {k: v for k, v in checkpoint(saver, thread_id).items() if k != "trace"}
    store = MemoryChatStore()
    write(store, replay(thread_id, values, 1_000, []))
    step = store.get_thread(thread_id).turns[0].steps[0]
    assert (step.count, step.ms, len(step.rows)) == (2, None, 2)
    assert {"pr:1", "issue:11"} <= {n["uid"] for n in step.nodes}
