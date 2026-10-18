"""The Claude agent loop with a scripted fake client: no network, no database."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from agents import ask as agent
from agents import llm, loop
from agents.testing import (  # noqa: F401  (settings: autouse fixture)
    TOOLSET,
    FakeClient,
    FakeTool,
    reply,
    settings,
    submit,
    text,
    tool_use,
)
from agents.toolset import Toolset
from brain.config import get_settings
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel


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


def test_request_shape_uses_settings_and_a_stable_prefix():
    client = FakeClient(reply(submit("t1", "Nothing found.", [])))
    ask(client)
    req = client.requests[0]
    assert req["model"] == "claude-haiku-5-5"
    assert req["output_config"] == {"effort": "medium"}
    assert "fallbacks" not in req  # Haiku has no server-side fallback
    assert req["betas"] == ["thinking-binding-controls-2026-08-01"]
    assert req["cache_control"] == {"type": "ephemeral"}
    assert "tool_choice" not in req  # forced tool choice is rejected by current models
    assert req["thinking"] == {
        "type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "drop_block"},
    }  # fmt: skip
    assert [t["name"] for t in req["tools"]] == ["related_work_items", loop.SUBMIT]
    assert req["tools"][0]["input_schema"]["required"] == ["text"]
    assert req["system"] == [{"type": "text", "text": loop.SYSTEM_PROMPT}]
    assert req["messages"][0]["content"][0]["text"].startswith("Company: Synthetic Co (synthetic)")


def test_prompt_says_how_to_use_a_semantic_search_hit():
    """A hit is cited by its source uid; its chunk_uid opens the whole passage. No dates: the
    prompt must stay a cacheable constant."""
    bullet = next(b for b in loop.SYSTEM_PROMPT.split("\n- ") if "`semantic_search` once" in b)
    assert "`uid`" in bullet and "`chunk_uid`" in bullet and "`get_entity`" in bullet


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


def test_markers_with_empty_sources_get_the_uids_they_could_cite():
    """Haiku sometimes writes its sources inside the answer text and leaves `sources` empty;
    when cut_leak cannot read them (here: a cut-off list), the refusal names the empty field,
    the seen uids, and the leaked part."""
    leaked = 'Load [1].</answer>\n<parameter name="sources">["pr:1'
    client = FakeClient(
        reply(tool_use("t1", "related_work_items", {"text": "jwt"})),
        reply(submit("t2", leaked, [])),
        reply(submit("t3", "Load [1].", ["pr:1"])),
    )
    a = ask(client)
    refusal = client.requests[2]["messages"][-1]["content"][0]
    assert refusal["is_error"] is True
    assert "sources is empty" in refusal["content"]
    assert 'pr:1 "Switch sessions to JWT"' in refusal["content"]
    assert '<parameter name="sources">' in refusal["content"]  # names the leaked part
    assert a.text == "Load [1]." and [s.uid for s in a.sources] == ["pr:1"]


def test_empty_sources_refusal_skips_the_leak_hint_without_a_leak():
    problem = loop.check_answer(
        {"answer": "Load [1].", "sources": [], "path": []},
        {"pr:1": {"uid": "pr:1", "title": "Switch sessions to JWT"}},
    )
    assert "sources is empty" in problem and "pr:1" in problem and "<parameter" not in problem


def test_repeated_refused_submits_end_the_question_without_an_answer():
    """The degenerate loop from the Haiku evals: the same empty-sources submit again and
    again. After MAX_REFUSALS refusals the turn ends; no further Claude call is made."""
    saver = InMemorySaver()
    client = FakeClient(
        reply(tool_use("t1", "related_work_items", {"text": "jwt"})),
        *[reply(submit(f"s{i}", "Load [1].", [])) for i in range(loop.MAX_REFUSALS)],
        reply(submit("u1", "Load [1].", [])),  # second question: its count starts at 0
        reply(submit("u2", "Load [1].", ["pr:1"])),
    )
    first = ask(client, checkpointer=saver)
    assert first.text is None and first.stop == "no_answer"
    assert len(client.requests) == 1 + loop.MAX_REFUSALS
    # Every refused submit got its error result, so the thread stays valid for a follow-up.
    last = saver.get_tuple({"configurable": {"thread_id": first.thread_id}})
    final = last.checkpoint["channel_values"]["messages"][-1]
    assert final["role"] == "user" and final["content"][0]["is_error"] is True

    second = agent.ask(
        "synthetic", "Sure?", first.thread_id, client=client, toolset=TOOLSET, checkpointer=saver
    )
    assert second.text == "Load [1]." and not client.replies


def test_a_leaked_parameter_tail_is_cut_from_the_answer_but_not_from_the_history():
    """Haiku sometimes writes the next parameter into the answer text; the Ask page must not
    show it, and the replayed assistant content must stay exactly as returned."""
    leaked = 'Load [1].</answer>\n<parameter name="sources">["pr:1"]'
    saver = InMemorySaver()
    client = FakeClient(
        reply(tool_use("t1", "related_work_items", {"text": "jwt"})),
        reply(submit("t2", leaked, ["pr:1"])),
    )
    a = ask(client, checkpointer=saver)
    assert a.text == "Load [1]." and [s.uid for s in a.sources] == ["pr:1"]
    assert len(client.requests) == 2  # accepted as is: no extra round trip
    last = saver.get_tuple({"configurable": {"thread_id": a.thread_id}})
    sent = last.checkpoint["channel_values"]["messages"][-2]
    assert sent["role"] == "assistant" and sent["content"][0]["input"]["answer"] == leaked


def test_leaked_sources_fill_an_empty_sources_field():
    client = FakeClient(
        reply(tool_use("t1", "related_work_items", {"text": "jwt"})),
        reply(submit("t2", 'Load [1].</answer>\n<parameter name="sources">["pr:1"]', [])),
    )
    a = ask(client)
    assert a.text == "Load [1]." and [s.uid for s in a.sources] == ["pr:1"]
    assert len(client.requests) == 2


def test_leaked_sources_are_checked_like_real_ones():
    client = FakeClient(
        reply(tool_use("t1", "related_work_items", {"text": "jwt"})),
        reply(submit("t2", 'Load [1].</answer>\n<parameter name="sources">["pr:999"]', [])),
        reply(submit("t3", "Load [1].", ["pr:1"])),
    )
    a = ask(client)
    rejected = client.requests[2]["messages"][-1]["content"][0]
    assert rejected["is_error"] is True and "pr:999" in rejected["content"]
    assert a.text == "Load [1]."


@pytest.mark.parametrize(
    ("text", "sources", "path", "want"),
    [
        # The three shapes in the Haiku eval runs.
        ('A [1].</answer>\n<parameter name="sources">["pr:2", "pr:1"]', ["pr:1", "pr:2"], [],
         {"answer": "A [1].", "sources": ["pr:1", "pr:2"], "path": []}),  # real field wins
        ("A.</answer>\n<parameter name=\"path\">[]", [], [],
         {"answer": "A.", "sources": [], "path": []}),
        ("A [1].</answer>\nsources and path follow.</answer>\n", ["pr:1"], ["pr:1"],
         {"answer": "A [1].", "sources": ["pr:1"], "path": ["pr:1"]}),
        # Path too, when the real field is empty.
        ('A [1].\n<parameter name="sources">["pr:1"]\n<parameter name="path">["person:a"]', [],
         [], {"answer": "A [1].", "sources": ["pr:1"], "path": ["person:a"]}),
        # Markers that still cite nothing: left whole, so the refusal can name the leak.
        ('A [1].</answer>\n<parameter name="sources">[pr:1', [], [], None),
        ("A [1].", [], [], None),  # nothing leaked
    ],
)  # fmt: skip
def test_cut_leak(text, sources, path, want):
    given = {"answer": text, "sources": sources, "path": path}
    assert loop.cut_leak(given) == (want or given)
    assert given == {"answer": text, "sources": sources, "path": path}  # never edited in place


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


def test_each_turn_of_a_thread_can_pick_its_model():
    saver = InMemorySaver()
    client = FakeClient(
        reply(submit("t1", "No sources.", [])),
        reply(submit("t2", "Still none.", [])),
        reply(submit("t3", "None again.", [])),
    )
    first = ask(client, checkpointer=saver, model="claude-opus-5-5")
    agent.ask("synthetic", "Sure?", first.thread_id, client=client, toolset=TOOLSET,
              checkpointer=saver)  # fmt: skip
    agent.ask("synthetic", "Haiku?", first.thread_id, client=client, toolset=TOOLSET,
              checkpointer=saver, model="claude-haiku-5-5")  # fmt: skip
    opus, default, haiku = client.requests
    assert opus["model"] == "claude-opus-5-5" and opus["fallbacks"] == "default"
    assert default["model"] == get_settings().anthropic_model  # no model: back to the default
    assert haiku["model"] == "claude-haiku-5-5" and "fallbacks" not in haiku
    assert len(haiku["messages"]) == 7  # the Opus turns are kept as they were (append-only)


def test_an_unknown_model_is_refused_before_any_call():
    client = FakeClient()
    with pytest.raises(ValueError, match="unknown model"):
        ask(client, model="claude-opus-4-1")
    assert client.requests == []


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
    from agents.toolset import graph_toolset

    defs = graph_toolset().definitions()
    names = [d["name"] for d in defs]
    assert names == sorted(names) and "related_work_items" in names and "get_entity" in names
    assert all("title" not in d["input_schema"] and d["description"] for d in defs)


def test_rows_keyed_by_person_uid_are_citable_with_a_title():
    from agents.toolset import _collect_nodes

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
    monkeypatch.setattr(agent, "RECURSION_LIMIT", 3)  # call, tools, call -> stops
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


def test_a_question_goes_straight_to_the_brain_loop():
    client = FakeClient(reply(submit("t1", "Nothing found.", [])))
    assert ask(client).text == "Nothing found." and len(client.requests) == 1


def test_offline_client_runs_a_scripted_turn_through_the_real_loop():
    from agents.offline import OfflineClient

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


@pytest.mark.parametrize("model", ["claude-sonnet-5-5", "claude-opus-5-5"])
def test_sonnet_and_opus_get_server_side_fallbacks(monkeypatch, model):
    monkeypatch.setenv("ANTHROPIC_MODEL", model)
    get_settings.cache_clear()
    client = FakeClient(reply(submit("t1", "Nothing found.", [])))
    ask(client)
    req = client.requests[0]
    assert req["model"] == model
    assert req["fallbacks"] == "default"
    assert req["betas"] == [llm.THINKING_BINDING_BETA, "server-side-fallback-2026-07-01"]


@pytest.mark.parametrize("model", [m.id for m in llm.MODELS])
def test_every_model_drops_thinking_made_under_an_old_prompt(monkeypatch, model):
    """A thread asked before a deploy changed the prompt or tools replays thinking blocks bound
    to the old prefix; without drop_block the API answers 400 ("bound to a different
    conversation"). block_binding is accepted only with adaptive thinking."""
    monkeypatch.setenv("ANTHROPIC_MODEL", model)
    get_settings.cache_clear()
    client = FakeClient(reply(submit("t1", "Nothing found.", [])))
    ask(client)
    req = client.requests[0]
    assert req["thinking"] == llm.THINKING and req["thinking"]["type"] == "adaptive"
    assert req["betas"][0] == llm.THINKING_BINDING_BETA
