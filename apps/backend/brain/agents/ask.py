"""Ask a company graph a question; Claude answers with cited sources.

Why: the product promise is "sources and graph paths behind every answer". A LangGraph loop
drives Claude (Anthropic SDK) over the named graph tools:

    START -> call_claude --tool_use--> run_tools --(answer accepted)--> END
                 ^                         |
                 +-------------------------+
             call_claude --(end_turn without an answer)--> nudge -> call_claude
             call_claude --(refusal / max_tokens)--> END

The graph owns the loop (not the SDK tool runner), so every step is checkpointed: with a
checkpointer, a `thread_id` turns follow-up questions into one conversation.

Rules the loop keeps:
- State holds messages in Anthropic's own block format and is append-only. Assistant content is
  stored exactly as returned (thinking blocks included); the API rejects edited history.
- All tool results of one assistant turn go back in a single user message.
- The answer arrives through the `submit_answer` tool (the current models reject forced tool
  choice, so the system prompt asks for it). Cited uids must have appeared in a tool result in
  this thread; otherwise Claude gets an error result and tries again.
"""

from __future__ import annotations

import operator
import uuid
from dataclasses import dataclass, field
from importlib import resources
from typing import Annotated, Any, Literal, TypedDict

import anthropic
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from brain import llm
from brain.agents.toolset import Toolset, graph_toolset
from brain.config import get_settings, load_company

SYSTEM_PROMPT = resources.files("brain.agents").joinpath("system_prompt.md").read_text()
SUBMIT = "submit_answer"
MAX_NUDGES = 1  # times we ask for submit_answer after a plain-text reply before giving up
RECURSION_LIMIT = 40  # graph steps per question (each tool round trip is two)

SUBMIT_TOOL: dict[str, Any] = {
    "name": SUBMIT,
    "description": (
        "Submit the final answer with its sources. Call this exactly once, when you are done "
        "looking things up. Every uid in sources and path must come from an earlier tool result."
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
    answer: dict[str, Any] | None  # the accepted submit_answer input
    stop: str | None  # last stop_reason, or "no_answer"
    stop_details: dict[str, Any] | None
    model: str | None  # the model that served the last call (differs after a fallback)
    nudges: int


@dataclass
class Source:
    uid: str
    title: str | None = None
    url: str | None = None
    label: str | None = None


@dataclass
class Answer:
    question: str
    thread_id: str
    text: str | None  # None when Claude refused or stopped without an answer
    sources: list[Source] = field(default_factory=list)
    path: list[Source] = field(default_factory=list)
    stop: str | None = None
    stop_details: dict[str, Any] | None = None
    model: str | None = None
    usage: dict[str, int] = field(default_factory=dict)  # summed over this question's calls


# --- nodes ------------------------------------------------------------------------------------


def build_graph(
    client: anthropic.Anthropic,
    toolset: Toolset,
    checkpointer: BaseCheckpointSaver | None = None,
):
    s = get_settings()
    tool_defs = [*toolset.definitions(), SUBMIT_TOOL]

    def call_claude(state: AgentState) -> dict[str, Any]:
        with client.beta.messages.stream(
            model=s.anthropic_model,
            max_tokens=s.anthropic_max_tokens,
            system=[{"type": "text", "text": SYSTEM_PROMPT}],
            tools=tool_defs,
            messages=state["messages"],
            output_config={"effort": s.anthropic_effort},
            cache_control={"type": "ephemeral"},
            betas=[llm.FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            msg = stream.get_final_message()
        details = getattr(msg, "stop_details", None)
        content = replayable(msg.content)
        if msg.stop_reason == "max_tokens":
            # A tool call cut off mid-input never runs; an unanswered tool_use would make the
            # next request in this thread invalid. Nothing has been sent back yet, so drop it.
            content = [b for b in content if b["type"] != "tool_use"]
        return {
            # An empty turn (e.g. a refusal before any output) has nothing to replay.
            "messages": [{"role": "assistant", "content": content}] if content else [],
            "usage": [msg.usage.model_dump(mode="json", exclude_none=True)],
            "stop": msg.stop_reason,
            "stop_details": details.model_dump(mode="json") if details else None,
            "model": msg.model,
        }

    def run_tools(state: AgentState) -> dict[str, Any]:
        uses = [b for b in state["messages"][-1]["content"] if b["type"] == "tool_use"]
        seen = dict(state.get("seen") or {})
        results: list[dict[str, Any]] = []
        new_seen: dict[str, dict[str, Any]] = {}
        # Graph tools first, so a submit_answer in the same turn can cite their results.
        for use in sorted(uses, key=lambda u: u["name"] == SUBMIT):
            if use["name"] == SUBMIT:
                continue
            out = toolset.call(state["slug"], use["name"], use.get("input"))
            new_seen.update(out.seen)
            results.append(_result(use["id"], out.content, out.is_error))
        seen.update(new_seen)
        answer = None
        for use in uses:
            if use["name"] != SUBMIT:
                continue
            problem = check_answer(use.get("input") or {}, seen)
            if problem:
                results.append(_result(use["id"], problem, True))
            else:
                answer = use["input"]
                results.append(_result(use["id"], "Answer recorded.", False))
        return {
            "messages": [{"role": "user", "content": results}],
            "seen": new_seen,
            "answer": answer,
        }

    def nudge(state: AgentState) -> dict[str, Any]:
        text = f"Call {SUBMIT} with your final answer and its sources."
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

    g = StateGraph(AgentState)
    g.add_node("call_claude", call_claude)
    g.add_node("run_tools", run_tools)
    g.add_node("nudge", nudge)
    g.add_edge(START, "call_claude")
    g.add_conditional_edges("call_claude", after_claude)
    g.add_conditional_edges("run_tools", after_tools)
    g.add_edge("nudge", "call_claude")
    return g.compile(checkpointer=checkpointer)


def _result(tool_use_id: str, content: str, is_error: bool) -> dict[str, Any]:
    block = {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
    return {**block, "is_error": True} if is_error else block


def check_answer(answer: dict[str, Any], seen: dict[str, Any]) -> str | None:
    """Why an answer can't be accepted, or None. Only uids from tool results may be cited."""
    if not isinstance(answer.get("answer"), str) or not answer["answer"].strip():
        return "answer is empty."
    unknown = [u for u in [*answer.get("sources", []), *answer.get("path", [])] if u not in seen]
    if unknown:
        return (
            f"These uids did not appear in any tool result: {', '.join(unknown)}. Look them up, "
            f"or remove them, then call {SUBMIT} again."
        )
    return None


_MODEL_INTERNAL = {"thinking", "redacted_thinking", "tool_use", "server_tool_use"}


def replayable(content: list[Any]) -> list[dict[str, Any]]:
    """Assistant content as dicts to send back next turn, unchanged except after a mid-output
    fallback: model-internal blocks before the last `fallback` marker belong to the model that
    declined, so they are dropped (the API's echo rule); text before it and everything after
    are kept."""
    blocks = [b.model_dump(mode="json", exclude_none=True) for b in content]
    marks = [i for i, b in enumerate(blocks) if b["type"] == "fallback"]
    if not marks:
        return blocks
    cut = marks[-1]
    return [b for i, b in enumerate(blocks) if i >= cut or b["type"] not in _MODEL_INTERNAL]


# --- entry point ------------------------------------------------------------------------------


def ask(
    slug: str,
    question: str,
    thread_id: str | None = None,
    *,
    client: anthropic.Anthropic | None = None,
    toolset: Toolset | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> Answer:
    """Answer one question about brain_<slug>. Pass the same thread_id (with a checkpointer)
    to ask a follow-up in the same conversation."""
    thread_id = thread_id or uuid.uuid4().hex[:12]
    graph = build_graph(client or llm.client(), toolset or graph_toolset(), checkpointer)
    company = load_company(slug).name
    first = {
        "role": "user",
        "content": [{"type": "text", "text": f"Company: {company} ({slug})\n\n{question}"}],
    }
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT}
    before = 0
    if checkpointer is not None:
        before = len(graph.get_state(config).values.get("usage", []))
    state = graph.invoke(
        {
            "slug": slug,
            "messages": [first],
            "answer": None,
            "stop": None,
            "stop_details": None,
            "nudges": 0,
        },
        config,
    )
    return _to_answer(question, thread_id, state, state.get("usage", [])[before:])


def _to_answer(question: str, thread_id: str, state: dict, usage: list[dict]) -> Answer:
    seen = state.get("seen") or {}

    def source(uid: str) -> Source:
        node = seen.get(uid, {})
        return Source(
            uid=uid, title=node.get("title"), url=node.get("url"), label=node.get("label")
        )

    totals: dict[str, int] = {}
    for u in usage:
        for k, v in u.items():
            if isinstance(v, int):
                totals[k] = totals.get(k, 0) + v
    answer = state.get("answer")
    stop = state.get("stop")
    return Answer(
        question=question,
        thread_id=thread_id,
        text=answer["answer"] if answer else None,
        sources=[source(u) for u in answer["sources"]] if answer else [],
        path=[source(u) for u in answer["path"]] if answer else [],
        stop=stop if answer or stop in ("refusal", "max_tokens") else "no_answer",
        stop_details=state.get("stop_details"),
        model=state.get("model"),
        usage=totals,
    )
