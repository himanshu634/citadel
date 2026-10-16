"""MCP servers through the API's MCP connector, with the scripted client: what the request
carries, what an answer may cite, how MCP blocks replay in a thread, and the chat history."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from agents import ask as agent
from agents import llm, loop, mcp
from agents.history import MemoryChatStore
from agents.testing import (  # noqa: F401  (settings: autouse fixture)
    TOOLSET,
    FakeClient,
    mcp_call,
    mcp_listing,
    record_run,
    reply,
    settings,
    submit,
    text,
    tool_use,
)
from brain.config import McpServer, get_settings, load_company
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

HANDBOOK = {"name": "handbook", "url": "https://handbook.example/mcp", "token_env": "HB_TOKEN"}
DOCS = {"name": "docs", "url": "https://docs.example/mcp", "allowed_tools": ["search", "read"]}


@pytest.fixture
def servers(monkeypatch):
    """Give the synthetic company MCP servers; returns a setter for a different list."""
    monkeypatch.setenv("HB_TOKEN", "secret-token")
    real = load_company("synthetic")

    def use(*entries):
        cfg = real.model_copy(update={"mcp_servers": [McpServer(**e) for e in entries]})
        monkeypatch.setattr(agent, "load_company", lambda slug: cfg)

    use(HANDBOOK, DOCS)
    return use


def ask(client, question="Why JWT?", thread_id=None, saver=None):
    return agent.ask("synthetic", question, thread_id, client=client, toolset=TOOLSET,
                     checkpointer=saver)  # fmt: skip


SEARCH = mcp_call("m1", "handbook", "search_docs", "Sessions use JWT since 2025.")


# --- the request ------------------------------------------------------------------------------


def test_a_company_without_servers_sends_no_mcp():
    client = FakeClient(reply(submit("t1", "Nothing found.", [])))
    ask(client)
    req = client.requests[0]
    assert "mcp_servers" not in req and "betas" not in req
    assert [t.get("type") for t in req["tools"]] == [None, None]


def test_servers_and_toolsets_go_on_the_request(servers):
    client = FakeClient(reply(submit("t1", "Nothing found.", [])))
    ask(client)
    req = client.requests[0]
    assert req["betas"] == [mcp.BETA] == ["mcp-client-2026-09-15"]
    assert req["mcp_servers"] == [  # sorted by name; the token comes from its env var
        {"type": "url", "url": "https://docs.example/mcp", "name": "docs"},
        {"type": "url", "url": "https://handbook.example/mcp", "name": "handbook",
         "authorization_token": "secret-token"},
    ]  # fmt: skip
    # Graph tools, submit_answer, then one toolset per server: static for the company.
    assert req["tools"][:2] == [*TOOLSET.definitions(), loop.SUBMIT_TOOL]
    assert req["tools"][2:] == [
        {"type": "mcp_toolset", "mcp_server_name": "docs", "default_config": {"enabled": False},
         "configs": {"read": {"enabled": True}, "search": {"enabled": True}}},
        {"type": "mcp_toolset", "mcp_server_name": "handbook"},
    ]  # fmt: skip


def test_the_mcp_beta_joins_the_fallback_beta(servers, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    get_settings.cache_clear()
    client = FakeClient(reply(submit("t1", "Nothing found.", [])))
    ask(client)
    req = client.requests[0]
    assert req["betas"] == ["server-side-fallback-2026-07-01", mcp.BETA]
    assert req["fallbacks"] == "default"


def test_a_missing_token_fails_the_question_with_a_sentence(servers, monkeypatch):
    monkeypatch.delenv("HB_TOKEN")
    monkeypatch.setattr(mcp, "env_value", lambda name: None)  # no .env fallback either
    with pytest.raises(mcp.McpTokenMissing) as caught:
        ask(FakeClient())
    assert "set HB_TOKEN" in llm.describe_error(caught.value)


def test_server_config_is_validated():
    with pytest.raises(ValidationError):
        McpServer(name="docs", url="http://docs.example/mcp")  # https only
    with pytest.raises(ValidationError):
        McpServer(name="docs", url="https://docs.example/mcp", token_env="lower")
    with pytest.raises(ValidationError, match="unique"):
        load_company("synthetic").model_validate(
            {**load_company("synthetic").model_dump(), "mcp_servers": [DOCS, DOCS]}
        )


# --- citing what an MCP server returned -------------------------------------------------------


def test_an_answer_cites_an_mcp_result_by_server_and_tool(servers):
    client = FakeClient(
        reply(mcp_listing("handbook", "search_docs"), *SEARCH,
              submit("t1", "Sessions use JWT [1].", ["mcp:handbook/search_docs"])),
    )  # fmt: skip
    a = ask(client)
    assert a.text == "Sessions use JWT [1]."
    [src] = a.sources
    assert (src.uid, src.label, src.title, src.step) == (
        "mcp:handbook/search_docs", "MCP", "search_docs on handbook", None)  # fmt: skip


def test_citing_an_mcp_source_that_never_ran_is_rejected_with_a_hint(servers):
    failed = mcp_call("m2", "docs", "search", "server error", is_error=True)
    client = FakeClient(
        reply(*SEARCH, *failed, submit("t1", "Docs say so [1].", ["mcp:docs/search"])),
        reply(submit("t2", "The handbook says so [1].", ["mcp:handbook/search_docs"])),
    )
    a = ask(client)
    problem = client.requests[1]["messages"][-1]["content"][0]
    assert problem["is_error"]
    assert "mcp:docs/search" in problem["content"]  # a failed call is not citable
    assert "MCP results you may cite: mcp:handbook/search_docs." in problem["content"]
    assert a.text == "The handbook says so [1]."


def test_an_mcp_source_cannot_be_on_the_graph_path(servers):
    client = FakeClient(
        reply(*SEARCH, submit("t1", "JWT [1].", ["mcp:handbook/search_docs"],
                              ["mcp:handbook/search_docs"])),
        reply(submit("t2", "JWT [1].", ["mcp:handbook/search_docs"])),
    )  # fmt: skip
    ask(client)
    problem = client.requests[1]["messages"][-1]["content"][0]["content"]
    assert problem.startswith("path holds graph uids only")


# --- replay -----------------------------------------------------------------------------------


def test_mcp_blocks_replay_unchanged_in_a_follow_up(servers):
    saver = InMemorySaver()
    turn_one = reply(text("Checking."), mcp_listing("handbook", "search_docs"), *SEARCH,
                     tool_use("t1", "related_work_items", {"text": "jwt"}))  # fmt: skip
    client = FakeClient(
        turn_one,
        reply(submit("t2", "JWT [1][2].", ["mcp:handbook/search_docs", "pr:1"])),
        reply(submit("t3", "Still JWT [1].", ["mcp:handbook/search_docs"])),  # seen in turn one
    )
    first = ask(client, saver=saver)
    second = ask(client, "Sure?", first.thread_id, saver)
    assert second.text == "Still JWT [1]."

    history = client.requests[2]["messages"]
    sent = [b.model_dump(mode="json", exclude_none=True) for b in turn_one.content]
    assert history[1] == {"role": "assistant", "content": sent}  # listing included, byte for byte
    assert [b["type"] for b in history[1]["content"]] == [
        "text", "mcp_tool_listing", "mcp_tool_use", "mcp_tool_result", "tool_use"]  # fmt: skip
    assert client.requests[2]["betas"] == [mcp.BETA]
    assert client.requests[2]["tools"] == client.requests[0]["tools"]  # same prefix every call


def test_a_thread_with_mcp_blocks_keeps_the_header_after_servers_are_removed(servers):
    saver = InMemorySaver()
    client = FakeClient(
        reply(*SEARCH, submit("t1", "JWT [1].", ["mcp:handbook/search_docs"])),
        reply(submit("t2", "Yes.", [])),
    )
    first = ask(client, saver=saver)
    servers()  # the company drops its servers
    ask(client, "Sure?", first.thread_id, saver)
    req = client.requests[1]
    assert req["betas"] == [mcp.BETA] and "mcp_servers" not in req


def test_a_cut_off_mcp_call_is_not_replayed(servers):
    saver = InMemorySaver()
    use, _ = SEARCH
    client = FakeClient(
        reply(text("Looking"), use, stop="max_tokens"), reply(submit("t1", "?", []))
    )
    first = ask(client, saver=saver)
    assert first.stop == "max_tokens"
    ask(client, "Again?", first.thread_id, saver)
    assert client.requests[1]["messages"][1]["content"] == [{"type": "text", "text": "Looking"}]


def test_replayable_keeps_paired_mcp_calls_before_a_fallback():
    use, result = SEARCH
    lone, _ = mcp_call("m9", "handbook", "read", "never answered")
    marker = SimpleNamespace(model_dump=lambda **_: {"type": "fallback"})
    thinking = SimpleNamespace(model_dump=lambda **_: {"type": "thinking"})
    out = loop.replayable([thinking, use, result, lone, text("so far"), marker, thinking])
    assert [(b["type"], b.get("id") or b.get("tool_use_id")) for b in out] == [
        ("mcp_tool_use", "m1"), ("mcp_tool_result", "m1"), ("text", None), ("fallback", None),
        ("thinking", None)]  # fmt: skip


# --- chat history -----------------------------------------------------------------------------


def test_an_mcp_call_is_recorded_and_its_citation_kept(servers):
    store = MemoryChatStore()
    client = FakeClient(
        reply(*SEARCH, submit("t1", "Sessions use JWT [1].", ["mcp:handbook/search_docs"])),
    )
    answer = record_run(store, "Why JWT?", client)
    [turn] = store.get_thread(answer.thread_id).turns
    call = next(s for s in turn.steps if s.kind == "mcp")
    assert (call.tool, call.server, call.status) == ("search_docs", "handbook", "done")
    assert call.result == "Sessions use JWT since 2025."
    assert store.refs["mcp:handbook/search_docs"]["label"] == "MCP"
    assert (f"{answer.thread_id}:1", "mcp:handbook/search_docs") in store.links
