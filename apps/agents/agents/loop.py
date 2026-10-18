"""The brain loop: Claude (Anthropic SDK) answering over the named graph tools.

    call_claude --tool_use--> run_tools --(answer accepted)--> END
         ^                        |
         +------------------------+
    call_claude --(end_turn without an answer)--> nudge -> call_claude
    call_claude --(refusal / max_tokens)--> END

The graph owns the loop (not the SDK tool runner), so every step is checkpointed. Rules it keeps:
- State holds messages in Anthropic's own block format and is append-only. Assistant content is
  stored exactly as returned (thinking blocks included); the API rejects edited history.
- All tool results of one assistant turn go back in a single user message.
- The answer arrives through the `submit_answer` tool (the current models reject forced tool
  choice, so the system prompt asks for it). Cited uids must have appeared in a tool result in
  this thread; otherwise Claude gets an error result and tries again.
- A company's MCP servers (`agents/mcp.py`) run inside the Claude call: their `mcp_tool_use` /
  `mcp_tool_result` blocks arrive in the assistant content and replay with it; run_tools never
  sees them. A successful MCP call is citable as `mcp:<server>/<tool>`.
"""

from __future__ import annotations

import contextvars
import json
import operator
import re
import time
from collections.abc import Callable
from importlib import resources
from typing import Annotated, Any, Literal, TypedDict

import anthropic
from brain.config import get_settings
from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph

from agents import llm
from agents import mcp as mcp_
from agents.toolset import Toolset
from agents.walk import preview_rows, subgraph

SYSTEM_PROMPT = resources.files("agents").joinpath("system_prompt.md").read_text()
SUBMIT = "submit_answer"
MAX_NUDGES = 1  # times we ask for submit_answer after a plain-text reply before giving up
_MARKER = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")  # [1] or [1, 3]

SUBMIT_TOOL: dict[str, Any] = {
    "name": SUBMIT,
    "description": (
        "Submit the final answer with its sources. Call this exactly once, when you are done "
        "looking things up. Every uid in sources and path must come from an earlier tool result. "
        "A result from a tool on an MCP server has no uid: cite it in sources as "
        "mcp:<server>/<tool>."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "description": "Markdown with [n] markers; n is the 1-based index in sources.",
            },
            "sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "uids of the cited nodes, in marker order.",
            },
            "path": {
                "type": "array",
                "items": {"type": "string"},
                "description": "uids along the graph path that explains the answer, or [].",
            },
        },
        "required": ["answer", "sources", "path"],
        "additionalProperties": False,
    },
}


def _merge(a: dict, b: dict) -> dict:
    return {**a, **b}


class AgentState(TypedDict, total=False):
    slug: str
    messages: Annotated[list[dict[str, Any]], operator.add]
    seen: Annotated[dict[str, dict[str, Any]], _merge]  # uid -> {uid, label, title, url}
    usage: Annotated[list[dict[str, Any]], operator.add]  # one entry per Claude call
    answer: dict[str, Any] | None  # the accepted submit tool input (submit_answer for Q&A)
    stop: str | None  # last stop_reason, or "no_answer"
    stop_details: dict[str, Any] | None
    model: str | None  # the model that served the last call (differs after a fallback)
    ask_model: str | None  # the model this turn asked for (Ask page); None: ANTHROPIC_MODEL
    nudges: int
    trace: Annotated[list[dict[str, Any]], operator.add]  # one entry per tool call (run_tools)


ENTRY = "call_claude"  # where a turn enters this loop

# The id of the tool call run_tools is running: a tool that streams steps of its own (Ask's
# `ask_archivist`) hangs them off it.
CURRENT_STEP: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "CURRENT_STEP", default=None
)


Check = Callable[[dict[str, Any], dict[str, Any]], str | None]  # (input, seen) -> problem


def add_brain_loop(
    g: StateGraph,
    client: anthropic.Anthropic,
    toolset: Toolset,
    *,
    system_prompt: str = SYSTEM_PROMPT,
    submit_tool: dict[str, Any] = SUBMIT_TOOL,
    check: Check | None = None,  # default: check_answer
    mcp: mcp_.Connector | None = None,  # the company's MCP servers, if any
) -> str:
    """Add the loop's nodes and edges to `g`; returns the entry node name.

    The defaults are the brain's Q&A loop. Agent roles (`agents/runner.py`) pass their own
    prompt, their one submit tool and the check that grounds it; the loop is the same."""
    s = get_settings()
    check = check or check_answer
    submit = submit_tool["name"]
    tool_defs = [*toolset.definitions(), submit_tool, *(mcp.toolsets if mcp else ())]

    def call_claude(state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        # A thread may change model between turns: earlier thinking blocks stay in the history
        # unchanged (append-only); a model that cannot read another's blocks drops them itself.
        model = state.get("ask_model") or s.anthropic_model
        fallback = llm.fallback_params(model)
        extra = mcp_.request_params(mcp, state["messages"], fallback.pop("betas", []))
        with client.beta.messages.stream(
            model=model,
            max_tokens=s.anthropic_max_tokens,
            system=[{"type": "text", "text": system_prompt}],
            tools=tool_defs,
            messages=state["messages"],
            output_config={"effort": s.anthropic_effort},
            cache_control={"type": "ephemeral"},
            **fallback,
            **extra,
        ) as stream:
            msg = stream.get_final_message()
        details = getattr(msg, "stop_details", None)
        content = replayable(msg.content)
        if msg.stop_reason == "max_tokens":
            # A tool call cut off mid-input never runs; an unanswered tool_use (or an MCP or
            # server tool use without its result) would make the next request in this thread
            # invalid. Nothing has been sent back yet, so drop it.
            content = drop_unpaired([b for b in content if b["type"] != "tool_use"])
        writer = get_stream_writer()
        ms = round((time.perf_counter() - started) * 1000)
        writer(llm_event(content, msg, ms, submit))  # before its steps: they hang off it
        for b in content:
            if b["type"] == "tool_use":
                writer({"kind": "step", "id": b["id"], "tool": b["name"], "input": b.get("input")})
        found = mcp_.seen_from(content)
        return {
            # An empty turn (e.g. a refusal before any output) has nothing to replay.
            "messages": [{"role": "assistant", "content": content}] if content else [],
            **({"seen": found} if found else {}),
            "usage": [msg.usage.model_dump(mode="json", exclude_none=True)],
            "stop": msg.stop_reason,
            "stop_details": details.model_dump(mode="json") if details else None,
            "model": msg.model,
        }

    def run_tools(state: AgentState) -> dict[str, Any]:
        uses = [b for b in state["messages"][-1]["content"] if b["type"] == "tool_use"]
        submits = [u for u in uses if u["name"] == submit]
        results: list[dict[str, Any]] = []
        new_seen: dict[str, dict[str, Any]] = {}
        trace: list[dict[str, Any]] = []
        writer = get_stream_writer()  # the Ask page draws each step as soon as it is done

        def record(entry: dict[str, Any]) -> None:
            trace.append(entry)
            writer({"kind": "step_done", **entry})

        # Graph tools first, so a submit_answer in the same turn can cite their results.
        for use in uses:
            if use["name"] == submit:
                continue
            started = time.perf_counter()
            token = CURRENT_STEP.set(use["id"])
            try:
                out = toolset.call(state["slug"], use["name"], use.get("input"))
            finally:
                CURRENT_STEP.reset(token)
            ms = round((time.perf_counter() - started) * 1000)
            new_seen.update(out.seen)
            results.append(result_block(use["id"], out.content, out.is_error))
            nodes, rels = subgraph(use["name"], out.params, out.rows)
            record(
                {
                    "id": use["id"],
                    "tool": use["name"],
                    "input": use.get("input") or {},
                    "ms": ms,
                    "count": len(out.rows),
                    "error": _error_text(out.content) if out.is_error else None,
                    "rows": preview_rows(out.rows),
                    "nodes": nodes,
                    "rels": rels,
                    "uids": sorted(out.seen),
                }
            )
        seen = {**(state.get("seen") or {}), **new_seen}
        answer = None
        for use in submits:
            problem = check(use.get("input") or {}, seen)
            if problem:
                results.append(result_block(use["id"], problem, True))
            else:
                answer = use["input"]
                results.append(result_block(use["id"], "Answer recorded.", False))
            record({"id": use["id"], "tool": submit, "input": {}, "error": problem})
        return {
            "messages": [{"role": "user", "content": results}],
            "seen": new_seen,
            "answer": answer,
            "trace": trace,
        }

    def nudge(state: AgentState) -> dict[str, Any]:
        text = f"Call {submit} with your final answer and its sources."
        return {
            "messages": [{"role": "user", "content": [{"type": "text", "text": text}]}],
            "nudges": state.get("nudges", 0) + 1,
        }

    def after_claude(state: AgentState) -> Literal["run_tools", "nudge", "call_claude", "__end__"]:
        stop = state.get("stop")
        if stop in ("refusal", "max_tokens"):
            return END
        if stop == "pause_turn":
            return "call_claude"
        if any(b["type"] == "tool_use" for b in state["messages"][-1]["content"]):
            return "run_tools"
        return "nudge" if state.get("nudges", 0) < MAX_NUDGES else END

    def after_tools(state: AgentState) -> Literal["call_claude", "__end__"]:
        return END if state.get("answer") else "call_claude"

    g.add_node("call_claude", call_claude)
    g.add_node("run_tools", run_tools)
    g.add_node("nudge", nudge)
    g.add_conditional_edges("call_claude", after_claude)
    g.add_conditional_edges("run_tools", after_tools)
    g.add_edge("nudge", "call_claude")
    return ENTRY


def result_block(tool_use_id: str, content: str, is_error: bool) -> dict[str, Any]:
    block = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
    return {**block, "is_error": True} if is_error else block


def _error_text(content: str) -> str:
    """The sentence inside a toolset error result ({"error": "..."})."""
    try:
        return str(json.loads(content).get("error") or content)
    except (ValueError, AttributeError):
        return content


def check_answer(answer: dict[str, Any], seen: dict[str, Any]) -> str | None:
    """Why an answer can't be accepted, or None. Only uids from tool results may be cited."""
    if not isinstance(answer.get("answer"), str) or not answer["answer"].strip():
        return "answer is empty."
    sources = answer.get("sources", [])
    path = answer.get("path", [])
    unknown = [u for u in [*sources, *path] if u not in seen]
    if unknown:
        outside = sorted(u for u, n in seen.items() if n.get("label") == mcp_.LABEL)
        hint = f" MCP results you may cite: {', '.join(outside)}." if outside else ""
        return (
            f"These uids did not appear in any tool result: {', '.join(unknown)}. Look them up, "
            f"or remove them, then call {SUBMIT} again.{hint}"
        )
    outside_path = [u for u in path if seen[u].get("label") == mcp_.LABEL]
    if outside_path:
        return (
            f"path holds graph uids only; move {', '.join(outside_path)} to sources and call "
            f"{SUBMIT} again."
        )
    markers = {int(n) for m in _MARKER.findall(answer["answer"]) for n in m.split(",")}
    bad = sorted(n for n in markers if not 1 <= n <= len(sources))
    if bad:
        return (
            f"Markers {bad} have no matching entry in sources ({len(sources)} given). "
            f"Marker [n] cites sources[n-1]; fix them and call {SUBMIT} again."
        )
    return None


RESULT_PREVIEW = 2000  # characters of an MCP or server tool result kept for the history
# Block types that are tool calls -> their kind (None: graph or submit, decided by name).
_CALL_KINDS = {"tool_use": None, "mcp_tool_use": "mcp", "server_tool_use": "server"}


def llm_event(content: list[dict[str, Any]], msg: Any, ms: int, submit: str) -> dict[str, Any]:
    """The `llm` event for one Claude response: what it said and thought, what it asked for,
    tokens and timing (chat history and the Ask page's timeline). `calls` lists every tool the
    response used in order: `graph` and `submit` calls (tool_use) run later in run_tools, so
    they have no result here; `mcp` (mcp_tool_use, through the MCP connector) and `server`
    (server_tool_use) calls ran on Anthropic's side and come with their result blocks."""
    results = {
        b["tool_use_id"]: b
        for b in content
        if b["type"].endswith("_tool_result") and "tool_use_id" in b
    }
    calls: list[dict[str, Any]] = []
    for b in content:
        if b["type"] not in _CALL_KINDS:
            continue
        kind = _CALL_KINDS[b["type"]]
        call = {
            "id": b["id"],
            "tool": b["name"],
            "kind": kind or ("submit" if b["name"] == submit else "graph"),
            "server": b.get("server_name"),
            "input": b.get("input") or {},
        }
        if kind and (res := results.get(b["id"])):
            text = _result_text(res)
            call["error"] = text if res.get("is_error") else None
            call["result"] = text[:RESULT_PREVIEW]
        calls.append(call)
    usage = msg.usage
    return {
        "kind": "llm",
        "text": "\n\n".join(b["text"] for b in content if b["type"] == "text") or None,
        "thinking": "\n\n".join(b.get("thinking") or "" for b in content
                                 if b["type"] == "thinking").strip() or None,
        "model": msg.model,
        "stop": msg.stop_reason,
        "ms": ms,
        "usage": {
            "input": usage.input_tokens or 0,
            "output": usage.output_tokens or 0,
            "cache_read": getattr(usage, "cache_read_input_tokens", None) or 0,
            "cache_write": getattr(usage, "cache_creation_input_tokens", None) or 0,
        },
        "calls": calls,
    }  # fmt: skip


def _result_text(block: dict[str, Any]) -> str:
    """The text of a server-side tool result block (a string, or text blocks, or anything)."""
    body = block.get("content")
    if isinstance(body, str):
        return body
    if isinstance(body, list):
        texts = [c.get("text", "") for c in body if isinstance(c, dict) and c.get("type") == "text"]
        if texts:
            return "\n".join(texts)
    return json.dumps(body, default=str)


_MODEL_INTERNAL = {"thinking", "redacted_thinking", "tool_use"}
_SERVER_USES = {"server_tool_use", "mcp_tool_use"}  # ran on Anthropic's side, with a result block


def replayable(content: list[Any]) -> list[dict[str, Any]]:
    """Assistant content as dicts to send back next turn, unchanged except after a mid-output
    fallback: the API's echo rule drops model-internal blocks before the last `fallback` marker
    (they belong to the model that declined) and server-side tool uses there that have no
    result. Text, paired server or MCP calls with their results, MCP tool listings and
    everything after the marker are kept."""
    blocks = [b.model_dump(mode="json", exclude_none=True) for b in content]
    marks = [i for i, b in enumerate(blocks) if b["type"] == "fallback"]
    if not marks:
        return blocks
    cut = marks[-1]
    before = drop_unpaired([b for b in blocks[:cut] if b["type"] not in _MODEL_INTERNAL])
    return before + blocks[cut:]


def drop_unpaired(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`blocks` without server or MCP tool uses that have no result block (cut off, or before
    a fallback): the API rejects them in history."""
    answered = {b["tool_use_id"] for b in blocks if "tool_use_id" in b}
    return [b for b in blocks if b["type"] not in _SERVER_USES or b["id"] in answered]
