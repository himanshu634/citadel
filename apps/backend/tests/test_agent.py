"""The Claude agent loop with a scripted fake client: no network, no database."""

from __future__ import annotations

import json
from contextlib import nullcontext
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from anthropic.types.beta import BetaTextBlock, BetaToolUseBlock, BetaUsage
from brain.agents import ask as agent
from brain.agents import loop
from brain.agents.toolset import Toolset
from brain.config import get_settings
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    """Pin the Claude settings so a local .env can't change what the tests expect."""
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("ANTHROPIC_EFFORT", "medium")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- fakes ------------------------------------------------------------------------------------


class SearchParams(BaseModel):
    text: str = Field(description="what to look for")
    limit: int = 10


class Row(BaseModel):
    uid: str
    title: str
    url: str | None = None
    author_uid: str | None = None


@dataclass
class FakeTool:
    name: str
    description: str
    params: type[BaseModel]


ROWS = [
    Row(uid="pr:1", title="Switch sessions to JWT", url="https://x/pr/1", author_uid="person:a"),
    Row(uid="issue:11", title="Session table load"),
]


def run(slug: str, name: str, **params) -> list[BaseModel]:
    assert slug == "synthetic"
    if params["text"] == "boom":
        raise RuntimeError("query failed")
    return ROWS[: params["limit"]]


TOOLSET = Toolset(
    tools={"related_work_items": FakeTool("related_work_items", "Find work items.", SearchParams)},
    run=run,
)


def tool_use(id_: str, name: str, inp: dict) -> BetaToolUseBlock:
    return BetaToolUseBlock(type="tool_use", id=id_, name=name, input=inp)


def text(t: str) -> BetaTextBlock:
    return BetaTextBlock(type="text", text=t)


def reply(*blocks, stop="tool_use", details=None):
    return SimpleNamespace(
        content=list(blocks),
        stop_reason=stop,
        stop_details=details,
        model="claude-sonnet-5-5",
        usage=BetaUsage(input_tokens=100, output_tokens=10, cache_read_input_tokens=80),
    )


class FakeClient:
    """Plays back scripted replies and records every request."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs)))  # snapshot, like the wire
        msg = self.replies.pop(0)
        return nullcontext(SimpleNamespace(get_final_message=lambda: msg))


def submit(id_: str, answer: str, sources: list[str], path: list[str] | None = None):
    return tool_use(id_, loop.SUBMIT, {"answer": answer, "sources": sources, "path": path or []})


def ask(client, **kw):
    return agent.ask("synthetic", "Why JWT?", client=client, toolset=TOOLSET, **kw)


# --- tests ------------------------------------------------------------------------------------


def test_tool_round_trip_ends_with_a_cited_answer():
    client = FakeClient(
        reply(
            tool_use("t1", "related_work_items", {"text": "jwt sessions"}),
            tool_use("t2", "related_work_items", {"text": "session load", "limit": 1}),
        ),
        reply(submit("t3", "Session load [1].", ["pr:1"], ["person:a", "pr:1"])),
    )
    a = ask(client)

    assert a.text == "Session load [1]."
    assert a.stop == "tool_use"
    assert [(s.uid, s.title, s.url) for s in a.sources] == [
        ("pr:1", "Switch sessions to JWT", "https://x/pr/1")
    ]
    assert [p.uid for p in a.path] == ["person:a", "pr:1"]  # bare *_uid values count as seen
    assert a.usage == {"input_tokens": 200, "output_tokens": 20, "cache_read_input_tokens": 160}

    # Both tool results went back in one user message, in call order.
    second = client.requests[1]["messages"]
    results = second[-1]["content"]
    assert second[-1]["role"] == "user"
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert json.loads(results[1]["content"])["count"] == 1
    # The assistant turn is replayed exactly as returned.
    assert second[-2] == {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "id": "t1", "name": "related_work_items",
             "input": {"text": "jwt sessions"}},
            {"type": "tool_use", "id": "t2", "name": "related_work_items",
             "input": {"text": "session load", "limit": 1}},
        ],
    }  # fmt: skip


def test_request_shape_uses_settings_fallbacks_and_a_stable_prefix():
    client = FakeClient(reply(submit("t1", "Nothing found.", [])))
    ask(client)
    req = client.requests[0]
    assert req["model"] == "claude-sonnet-5-5"
    assert req["output_config"] == {"effort": "medium"}
    assert req["fallbacks"] == "default"
    assert req["betas"] == ["server-side-fallback-2026-07-01"]
    assert req["cache_control"] == {"type": "ephemeral"}
    assert "tool_choice" not in req  # forced tool choice is rejected by current models
    assert "thinking" not in req
    assert [t["name"] for t in req["tools"]] == ["related_work_items", loop.SUBMIT]
    assert req["tools"][0]["input_schema"]["required"] == ["text"]
    assert req["system"] == [{"type": "text", "text": loop.SYSTEM_PROMPT}]
    assert req["messages"][0]["content"][0]["text"].startswith("Company: Synthetic Co (synthetic)")


def test_citing_an_unseen_uid_is_rejected_then_corrected():
    client = FakeClient(
        reply(tool_use("t1", "related_work_items", {"text": "jwt"})),
        reply(submit("t2", "Made up [1].", ["pr:999"])),
        reply(submit("t3", "Real [1].", ["issue:11"])),
    )
    a = ask(client)
    rejected = client.requests[2]["messages"][-1]["content"][0]
    assert rejected["is_error"] is True and "pr:999" in rejected["content"]
    assert a.text == "Real [1]." and a.sources[0].title == "Session table load"


def test_bad_tool_input_and_failing_query_come_back_as_error_results():
    client = FakeClient(
        reply(
            tool_use("t1", "related_work_items", {"limit": 3}),  # missing required text
            tool_use("t2", "related_work_items", {"text": "boom"}),
            tool_use("t3", "no_such_tool", {}),
        ),
        reply(submit("t4", "Could not find it.", [])),
    )
    a = ask(client)
    results = client.requests[1]["messages"][-1]["content"]
    assert [r.get("is_error") for r in results] == [True, True, True]
    assert "invalid input" in results[0]["content"]
    assert "query failed" in results[1]["content"]
    assert "unknown tool" in results[2]["content"]
    assert a.text == "Could not find it."


def test_plain_text_reply_gets_one_nudge():
    client = FakeClient(
        reply(text("It was for load."), stop="end_turn"),
        reply(submit("t1", "For load.", [])),
    )
    a = ask(client)
    nudge = client.requests[1]["messages"][-1]
    assert nudge["role"] == "user" and loop.SUBMIT in nudge["content"][0]["text"]
    assert a.text == "For load."


def test_second_plain_text_reply_ends_without_an_answer():
    client = FakeClient(
        reply(text("a"), stop="end_turn"),
        reply(text("b"), stop="end_turn"),
    )
    a = ask(client)
    assert a.text is None and a.stop == "no_answer"


def test_refusal_stops_and_reports_details():
    details = SimpleNamespace(
        model_dump=lambda mode=None: {"type": "refusal", "category": "cyber", "explanation": "x"}
    )
    a = ask(FakeClient(reply(stop="refusal", details=details)))
    assert a.text is None and a.stop == "refusal"
    assert a.stop_details["category"] == "cyber"


def test_thread_follow_up_appends_to_the_same_conversation():
    saver = InMemorySaver()
    client = FakeClient(
        reply(tool_use("t1", "related_work_items", {"text": "jwt"})),
        reply(submit("t2", "Load [1].", ["pr:1"])),
        reply(submit("t3", "Still load [1].", ["pr:1"])),  # cites a uid seen in turn one
    )
    first = ask(client, checkpointer=saver)
    second = agent.ask(
        "synthetic", "Sure?", first.thread_id, client=client, toolset=TOOLSET, checkpointer=saver
    )
    assert second.text == "Still load [1]."
    assert second.usage["input_tokens"] == 100  # only this question's call
    history = client.requests[2]["messages"]
    # question, tool call, tool results, submit, its result, follow-up question
    assert [m["role"] for m in history] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
        "user",
    ]
    assert history[-1]["content"][0]["text"].endswith("Sure?")


@pytest.mark.parametrize(
    ("types", "kept"),
    [
        (["thinking", "text", "tool_use"], ["thinking", "text", "tool_use"]),
        (
            ["thinking", "text", "tool_use", "fallback", "thinking", "tool_use"],
            ["text", "fallback", "thinking", "tool_use"],
        ),
    ],
)
def test_replayable_drops_declined_model_internals_before_a_fallback(types, kept):
    blocks = [SimpleNamespace(model_dump=lambda t=t, **_: {"type": t}) for t in types]
    assert [b["type"] for b in loop.replayable(blocks)] == kept


def test_real_tool_registry_becomes_sorted_tool_definitions():
    from brain.agents.toolset import graph_toolset

    defs = graph_toolset().definitions()
    names = [d["name"] for d in defs]
    assert names == sorted(names) and "related_work_items" in names and "get_entity" in names
    assert all("title" not in d["input_schema"] and d["description"] for d in defs)


def test_rows_keyed_by_person_uid_are_citable_with_a_title():
    from brain.agents.toolset import _collect_nodes

    seen: dict = {}
    _collect_nodes(
        [{"login": "alice", "person_uid": "person:alice", "system_uid": "system:Auth"}], seen
    )
    assert seen["person:alice"] == {"uid": "person:alice", "title": "alice"}
    assert seen["system:Auth"] == {"uid": "system:Auth"}


def test_out_of_range_citation_marker_is_rejected():
    client = FakeClient(
        reply(tool_use("t1", "related_work_items", {"text": "jwt"})),
        reply(submit("t2", "Load [2].", ["pr:1"])),
        reply(submit("t3", "Load [1].", ["pr:1"])),
    )
    a = ask(client)
    rejected = client.requests[2]["messages"][-1]["content"][0]
    assert rejected["is_error"] is True and "[2]" in rejected["content"]
    assert a.text == "Load [1]."


def test_step_limit_closes_open_tool_calls_so_the_thread_stays_valid(monkeypatch):
    monkeypatch.setattr(agent, "RECURSION_LIMIT", 4)  # router, call, tools, call -> stops
    saver = InMemorySaver()
    turns = [reply(tool_use(f"t{i}", "related_work_items", {"text": "jwt"})) for i in range(2)]
    client = FakeClient(*turns, reply(submit("t9", "Load [1].", ["pr:1"])))
    first = ask(client, checkpointer=saver)
    assert first.text is None and first.stop == "step_limit"

    monkeypatch.setattr(agent, "RECURSION_LIMIT", 40)
    second = agent.ask(
        "synthetic", "Try again", first.thread_id, client=client, toolset=TOOLSET,
        checkpointer=saver,
    )  # fmt: skip
    assert second.text == "Load [1]."
    history = client.requests[-1]["messages"]
    blocks = [b for m in history for b in m["content"]]
    calls = [b["id"] for b in blocks if b["type"] == "tool_use"]
    answered = [b["tool_use_id"] for b in blocks if b["type"] == "tool_result"]
    assert calls and calls == answered  # every tool call has its result, in order
    assert any("step limit" in str(b.get("content")) for b in blocks)  # the closing path ran


def test_router_sends_questions_to_the_brain_loop():
    from brain.agents import graph

    assert graph.router({}) == {"route": "brain"}
    client = FakeClient(reply(submit("t1", "Nothing found.", [])))
    assert ask(client).text == "Nothing found." and len(client.requests) == 1


def test_build_route_runs_the_placeholders_without_calling_claude(monkeypatch):
    from brain.agents import graph

    monkeypatch.setattr(graph, "router", lambda state: {"route": "build"})
    client = FakeClient()
    a = ask(client)
    assert client.requests == [] and a.text is None and a.stop == "no_answer"


def test_offline_client_runs_a_scripted_turn_through_the_real_loop():
    from brain.agents.offline import OfflineClient

    class SystemsParams(BaseModel):
        limit: int = 100

    class SystemRow(BaseModel):
        system: str
        system_uid: str

    toolset = Toolset(
        tools={"list_systems": FakeTool("list_systems", "List systems.", SystemsParams)},
        run=lambda slug, name, **p: [SystemRow(system="Auth", system_uid="system:Auth")],
    )
    saver = InMemorySaver()
    first = agent.ask("synthetic", "?", client=OfflineClient(), toolset=toolset, checkpointer=saver)
    assert first.text == "The graph has 1 systems: Auth [1]."
    assert [s.uid for s in first.sources] == ["system:Auth"] and first.sources[0].title == "Auth"
    again = agent.ask(
        "synthetic", "?", first.thread_id, client=OfflineClient(), toolset=toolset,
        checkpointer=saver,
    )  # fmt: skip
    assert again.thread_messages == 2 * first.thread_messages == 10
