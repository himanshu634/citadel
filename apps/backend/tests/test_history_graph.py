"""Chat history in FalkorDB: the queries/chat/ writes and reads (needs `make up`).

Each test writes to a throwaway agent_test_<hex> graph and deletes it afterwards.
"""

from __future__ import annotations

import uuid

import pytest
from brain import db
from brain.agents import history
from brain.agents.history import GraphChatStore
from brain.config import agent_graph_name
from conftest import needs_graph
from langgraph.checkpoint.memory import InMemorySaver
from tests.test_agent import FakeClient, reply, settings, submit, text, tool_use  # noqa: F401
from tests.test_history import record

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
    left = db.agent_graph(store.slug).query("MATCH (n) RETURN count(n)").result_set[0][0]
    assert left == 0
    assert not store.delete_thread(answer.thread_id)


def test_reading_a_company_with_no_chats_is_empty(store):
    assert store.list_threads(history.NEVER, 10) == [] and store.get_thread("nope") is None
