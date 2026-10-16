"""Ask a company graph a question; Claude answers with cited sources.

Why: the product promise is "sources and graph paths behind every answer". `ask` runs one turn
of the agent graph (`graph.py`: router -> brain loop in `loop.py`) and turns the final state
into an `Answer` with numbered sources. With a checkpointer, a `thread_id` turns follow-up
questions into one conversation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import anthropic
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphRecursionError

from brain import llm
from brain.agents.graph import build_graph
from brain.agents.loop import result_block
from brain.agents.toolset import Toolset, graph_toolset
from brain.config import load_company

RECURSION_LIMIT = 40  # graph steps per question (each tool round trip is two)


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
    thread_messages: int = 0  # messages saved in the thread after this turn


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
    inputs = {
        "slug": slug,
        "messages": [first],
        "answer": None,
        "stop": None,
        "stop_details": None,
        "nudges": 0,
        "route": None,
    }
    try:
        state = graph.invoke(inputs, config)
    except GraphRecursionError:
        state = {}
        if checkpointer is not None:
            _close_open_tool_calls(graph, config)
            state = graph.get_state(config).values
        state = {**state, "answer": None, "stop": "step_limit"}
    return _to_answer(question, thread_id, state, state.get("usage", [])[before:])


def _close_open_tool_calls(graph, config: dict) -> None:
    """After the step limit, the saved thread may end on tool calls that never ran. Answer them
    with error results (appended, never edited) so a follow-up in the thread stays valid."""
    messages = graph.get_state(config).values.get("messages") or []
    last = messages[-1] if messages else {}
    uses = [b for b in last.get("content", []) if b.get("type") == "tool_use"]
    if last.get("role") == "assistant" and uses:
        results = [
            result_block(u["id"], "Not run: the step limit was reached.", True) for u in uses
        ]
        graph.update_state(
            config, {"messages": [{"role": "user", "content": results}]}, as_node="run_tools"
        )


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
        stop=stop if answer or stop in ("refusal", "max_tokens", "step_limit") else "no_answer",
        stop_details=state.get("stop_details"),
        model=state.get("model"),
        usage=totals,
        thread_messages=len(state.get("messages") or []),
    )
