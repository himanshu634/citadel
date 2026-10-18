"""Chat history in FalkorDB: the queries/chat/ writes and reads (needs `make up`).

Each test writes to a throwaway agent_test_<hex> graph and deletes it afterwards.
"""

from __future__ import annotations

import uuid

import pytest
from agents import ask as agent
from agents import checkpoint, history
from agents.graphs import agent_graph_name
from agents.history import GraphChatStore
from agents.testing import (  # noqa: F401
    FakeClient,
    mcp_call,
    reply,
    settings,
    submit,
    text,
    tool_use,
)
from agents.testing import record_run as record
from brain import db
from brain.config import McpServer, load_company
from brain.testing import needs_graph
from langgraph.checkpoint.memory import InMemorySaver

pytestmark = needs_graph


@pytest.fixture
def store():
    slug = f"test_{uuid.uuid4().hex[:8]}"
    yield GraphChatStore(slug)
    name = agent_graph_name(slug)
    if name in db.client().list_graphs():
        db.client().select_graph(name).delete()


def test_a_run_reads_back_from_the_graph_as_it_was_written(store):
    client = FakeClient(
        reply(text("Let me look."), tool_use("t1", "related_work_items", {"text": "jwt"})),
        reply(submit("t2", "Sessions moved to JWT [1].", ["pr:1"])),
    )
    answer = record(store, "Why JWT?", client)
    [summary] = store.list_threads(history.NEVER, 10)
    assert (summary.id, summary.title, summary.turns, summary.last_status) == (
        answer.thread_id, "Why JWT?", 1, "done")  # fmt: skip

    thread = store.get_thread(answer.thread_id)
    [turn] = thread.turns
    assert (turn.status, turn.answer["text"], turn.answer["sources"][0]["uid"]) == (
        "done", "Sessions moved to JWT [1].", "pr:1")  # fmt: skip
    assert [(c.seq, c.text, c.usage.input) for c in turn.calls] == [
        (1, "Let me look.", 100), (2, None, 100)]  # fmt: skip
    graph, check = turn.steps
    assert (graph.id, graph.call, graph.n, graph.kind, graph.count, graph.input) == (
        "t1", 1, 1, "graph", 2, {"text": "jwt"})  # fmt: skip
    assert {n["uid"] for n in graph.nodes} == {"pr:1", "issue:11"} and graph.rows
    assert (check.call, check.kind, check.status) == (2, "submit", "done")
    assert [t.id for t in store.ref_threads("pr:1", 5)] == [answer.thread_id]
    assert [t.id for t in store.ref_threads("issue:11", 5)] == [answer.thread_id]  # touched


def test_an_mcp_call_and_its_citation_read_back_from_the_graph(store, monkeypatch):
    server = McpServer(name="handbook", url="https://handbook.example/mcp")
    cfg = load_company("synthetic").model_copy(update={"mcp_servers": [server]})
    monkeypatch.setattr(agent, "load_company", lambda slug: cfg)
    client = FakeClient(
        reply(*mcp_call("m1", "handbook", "search_docs", "JWT since 2025."),
              submit("t1", "JWT [1].", ["mcp:handbook/search_docs"])),
    )  # fmt: skip
    answer = record(store, "Why JWT?", client)
    [turn] = store.get_thread(answer.thread_id).turns
    mcp, check = turn.steps
    assert (mcp.kind, mcp.server, mcp.tool, mcp.n, mcp.status, mcp.result) == (
        "mcp", "handbook", "search_docs", None, "done", "JWT since 2025.")  # fmt: skip
    assert check.kind == "submit" and check.status == "done"
    assert [t.id for t in store.ref_threads("mcp:handbook/search_docs", 5)] == [answer.thread_id]


def test_turns_number_on_and_the_list_pages_newest_first(store):
    saver = InMemorySaver()
    first = record(store, "One?", FakeClient(reply(submit("a", "1.", []))), saver=saver)
    record(store, "Two?", FakeClient(reply(submit("b", "2.", []))), first.thread_id, saver)
    other = record(store, "Other?", FakeClient(reply(submit("c", "3.", []))))
    assert [t.n for t in store.get_thread(first.thread_id).turns] == [1, 2]
    page = store.list_threads(history.NEVER, 1)
    assert [t.id for t in page] == [other.thread_id]
    before = int(page[0].updated_at.timestamp() * 1000)
    assert [t.id for t in store.list_threads(before, 5)] == [first.thread_id]


def test_delete_removes_the_history_and_unused_refs(store):
    client = FakeClient(
        reply(tool_use("t1", "related_work_items", {"text": "jwt"})),
        reply(submit("t2", "JWT [1].", ["pr:1"])),
    )
    answer = record(store, "Why JWT?", client)
    assert store.delete_thread(answer.thread_id)
    assert store.get_thread(answer.thread_id) is None and not store.ref_threads("pr:1", 5)
    left = checkpoint.graph(store.slug).query("MATCH (n) RETURN count(n)").result_set[0][0]
    assert left == 0
    assert not store.delete_thread(answer.thread_id)


def test_reading_a_company_with_no_chats_is_empty(store):
    assert store.list_threads(history.NEVER, 10) == [] and store.get_thread("nope") is None


def test_archive_steps_read_back_nested_under_their_call(store):
    """The Archivist's calls inside ask_archivist (kind archive) keep their parent; a reopened
    thread nests them under it, in order, even when their ids repeat another run's."""
    rec = history.Recorder(store, "Why JWT?")
    call = {"id": "t1", "tool": "ask_archivist", "kind": "graph", "input": {"kind": "topic"}}
    llm = {"kind": "llm", "seq": 1, "usage": {}, "calls": [call]}
    inner = [
        ("p1_0", "archive_lookup"),
        ("p2_0", "archive_fetch"),
        ("p3_0", "submit_archive_answer"),
    ]
    rec.on({"kind": "start", "thread_id": "th_archive"})
    rec.on(llm)
    for id_, tool in inner:
        rec.on({"kind": "archive_step", "parent": "t1", "event": "step", "id": id_, "tool": tool})
        rec.on({"kind": "archive_step", "parent": "t1", "event": "step_done", "id": id_,
                "tool": tool, "input": {}, "ms": 3, "count": 1,
                "uids": ["synthetic:issue:900"]})  # fmt: skip
    rec.on({"kind": "step_done", "id": "t1", "n": 1, "tool": "ask_archivist", "input": {},
            "ms": 9, "count": 1})  # fmt: skip
    rec.answer({"kind": "answer", "text": "x", "sources": [], "stop": "end_turn"})
    [turn] = store.get_thread("th_archive").turns
    [outer] = turn.steps
    assert (outer.tool, outer.kind, outer.parent) == ("ask_archivist", "graph", None)
    assert [(s.id, s.tool, s.kind, s.parent, s.n) for s in outer.steps] == [
        ("p1_0", "archive_lookup", "archive", "t1", 1),
        ("p2_0", "archive_fetch", "archive", "t1", 2),
        ("p3_0", "submit_archive_answer", "archive", "t1", 3)]  # fmt: skip
    assert [t.id for t in store.ref_threads("synthetic:issue:900", 5)] == ["th_archive"]
