"""Chat history: the `llm` event and the Recorder, with a scripted Claude and the memory store."""

from __future__ import annotations

from anthropic.types.beta import (
    BetaMCPToolResultBlock,
    BetaMCPToolUseBlock,
    BetaTextBlock,
    BetaThinkingBlock,
)
from brain.agents import ask as agent
from brain.agents import history, loop
from brain.agents.history import MemoryChatStore, Recorder, title_of
from langgraph.checkpoint.memory import InMemorySaver
from tests.test_agent import TOOLSET, FakeClient, reply, settings, submit, text, tool_use  # noqa: F401


def record(store, question, client, thread_id=None, saver=None):
    """One run through the recorder, the way the Ask API drives it."""
    rec = Recorder(store, question)
    for event in agent.run_events(
        "synthetic", question, thread_id, client=client, toolset=TOOLSET, checkpointer=saver
    ):
        if isinstance(event, agent.Answer):
            rec.answer(agent.answer_out(event, "tr1"), event.model)
            return event
        rec.on(dict(event))
    raise AssertionError("no answer")


def test_llm_event_keeps_text_thinking_tokens_and_every_call():
    content = loop.replayable([
        BetaThinkingBlock(type="thinking", thinking="Look up JWT first.", signature="s"),
        BetaTextBlock(type="text", text="Checking the PRs."),
        BetaMCPToolUseBlock(type="mcp_tool_use", id="m1", name="search_docs",
                            server_name="docs", input={"q": "jwt"}),
        BetaMCPToolResultBlock(type="mcp_tool_result", tool_use_id="m1", is_error=False,
                               content=[BetaTextBlock(type="text", text="JWT RFC")]),
        tool_use("t1", "related_work_items", {"text": "jwt"}),
        submit("t2", "Done.", []),
    ])  # fmt: skip
    e = loop.llm_event(content, reply(), 42, loop.SUBMIT)
    assert (e["kind"], e["text"], e["thinking"], e["ms"]) == (
        "llm", "Checking the PRs.", "Look up JWT first.", 42)  # fmt: skip
    assert e["usage"] == {"input": 100, "output": 10, "cache_read": 80, "cache_write": 0}
    mcp, graph, check = e["calls"]
    assert (mcp["kind"], mcp["server"], mcp["result"], mcp["error"]) == (
        "mcp", "docs", "JWT RFC", None)  # fmt: skip
    assert (graph["kind"], graph["tool"], "result" in graph) == ("graph", "related_work_items",
                                                                 False)  # fmt: skip
    assert check["kind"] == "submit"


def test_a_failed_mcp_call_keeps_its_error():
    content = loop.replayable([
        BetaMCPToolUseBlock(type="mcp_tool_use", id="m1", name="x", server_name="s", input={}),
        BetaMCPToolResultBlock(type="mcp_tool_result", tool_use_id="m1", is_error=True,
                               content="server down"),
    ])  # fmt: skip
    [call] = loop.llm_event(content, reply(), 1, loop.SUBMIT)["calls"]
    assert call["error"] == "server down"


def test_a_run_becomes_a_thread_with_its_responses_calls_and_answer():
    store = MemoryChatStore()
    client = FakeClient(
        reply(text("Let me look."), tool_use("t1", "related_work_items", {"text": "jwt"})),
        reply(submit("t2", "Sessions moved to JWT [1].", ["pr:1"])),
    )
    answer = record(store, "Why JWT?", client)
    [summary] = store.list_threads(history.NEVER, 10)
    assert (summary.id, summary.title, summary.turns, summary.last_status) == (
        answer.thread_id, "Why JWT?", 1, "done")  # fmt: skip

    [turn] = store.get_thread(answer.thread_id).turns
    assert (turn.n, turn.question, turn.status, turn.ms is not None) == (1, "Why JWT?", "done",
                                                                         True)  # fmt: skip
    assert turn.answer["text"] == "Sessions moved to JWT [1]." and turn.answer["trace_id"] == "tr1"
    assert [(c.seq, c.text) for c in turn.calls] == [(1, "Let me look."), (2, None)]
    assert turn.calls[0].usage.input == 100
    graph, check = turn.steps
    assert (graph.call, graph.n, graph.kind, graph.status, graph.count) == (
        1,
        1,
        "graph",
        "done",
        2,
    )
    assert {n["uid"] for n in graph.nodes} == {"pr:1", "issue:11"} and graph.rows
    assert (check.call, check.kind, check.status) == (2, "submit", "done")
    assert store.refs["pr:1"]["title"] == "Switch sessions to JWT"
    assert (f"{answer.thread_id}:1", "pr:1") in store.links  # the turn cited it


def test_follow_ups_add_turns_to_the_same_thread():
    store, saver = MemoryChatStore(), InMemorySaver()
    first = record(store, "Why JWT?", FakeClient(reply(submit("t1", "No sources.", []))),
                   saver=saver)  # fmt: skip
    record(store, "Sure?", FakeClient(reply(submit("t2", "Yes.", []))), first.thread_id, saver)
    thread = store.get_thread(first.thread_id)
    assert [(t.n, t.question) for t in thread.turns] == [(1, "Why JWT?"), (2, "Sure?")]
    assert thread.title == "Why JWT?"


def test_a_rejected_answer_check_is_a_failed_step():
    store = MemoryChatStore()
    client = FakeClient(
        reply(tool_use("t1", "related_work_items", {"text": "jwt"})),
        reply(submit("t2", "Made up [1].", ["pr:999"])),
        reply(submit("t3", "Real [1].", ["pr:1"])),
    )
    answer = record(store, "Why JWT?", client)
    steps = store.get_thread(answer.thread_id).turns[0].steps
    assert [(s.kind, s.status) for s in steps] == [("graph", "done"), ("submit", "failed"),
                                                   ("submit", "done")]  # fmt: skip
    assert "pr:999" in steps[1].error


def test_a_failure_closes_the_turn_as_failed():
    store = MemoryChatStore()
    rec = Recorder(store, "Why?")
    rec.on({"kind": "start", "thread_id": "abc"})
    rec.fail("No Anthropic credentials.", "tr9")
    turn = store.get_thread("abc").turns[0]
    assert (turn.status, turn.error) == ("failed", "No Anthropic credentials.")
    assert store.threads["abc"]["last_status"] == "failed"


def test_a_store_that_fails_never_breaks_the_run():
    store = MemoryChatStore()
    store.fail = True
    answer = record(store, "Why?", FakeClient(reply(submit("t1", "Fine.", []))))
    assert answer.text == "Fine." and not store.threads


def test_titles_are_one_short_line():
    assert title_of("  Who\nknows   Auth? ") == "Who knows Auth?"
    long = title_of("x" * 200)
    assert len(long) == history.TITLE_CHARS and long.endswith("…")


def test_delete_drops_the_thread_and_refs_no_one_uses():
    store = MemoryChatStore()
    client = FakeClient(
        reply(tool_use("t1", "related_work_items", {"text": "jwt"})),
        reply(submit("t2", "JWT [1].", ["pr:1"])),
    )
    answer = record(store, "Why JWT?", client)
    assert [t.id for t in store.ref_threads("pr:1", 5)] == [answer.thread_id]
    assert store.delete_thread(answer.thread_id) and not store.delete_thread(answer.thread_id)
    assert not store.refs and not store.steps and store.get_thread(answer.thread_id) is None
