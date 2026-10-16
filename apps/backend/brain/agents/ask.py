"""Ask a company graph a question; Claude answers with cited sources.

Why: the product promise is "sources and graph paths behind every answer". `ask` runs one turn
of the agent graph (`graph.py`: router -> brain loop in `loop.py`) and turns the final state
into an `Answer` with numbered sources. With a checkpointer, a `thread_id` turns follow-up
questions into one conversation. `ask_events` is the same run as a stream of events (each tool
call as it is asked for and as it finishes, with the subgraph it touched), which the Ask page
draws as the agent's walk through the graph; `ask` is that stream's last item.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from typing import Any

import anthropic
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphRecursionError

from brain import llm
from brain.agents.graph import build_graph
from brain.agents.loop import SUBMIT, result_block
from brain.agents.toolset import Toolset, graph_toolset
from brain.config import load_company

_KEPT_STOPS = ("refusal", "max_tokens", "step_limit", "stopped")
RECURSION_LIMIT = 40  # graph steps per question (each tool round trip is two)


@dataclass
class Source:
    uid: str
    title: str | None = None
    url: str | None = None
    label: str | None = None
    step: int | None = None  # the step of this answer that first returned it (Ask page)


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
    nudges: int = 0  # plain-text replies this turn that were asked to call submit_answer
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
    for event in _run(slug, question, thread_id, client, toolset, checkpointer, None):
        if isinstance(event, Answer):
            return event
    raise AssertionError("the run ended without an answer")  # _run always ends with one


def ask_traced(
    slug: str,
    question: str,
    thread_id: str | None = None,
    *,
    client: anthropic.Anthropic | None = None,
    toolset: Toolset | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> tuple[Answer, list[dict[str, Any]]]:
    """`ask`, plus the run's `step_done` events (see `ask_events`), so evals can grade which
    tools ran and how often an answer was rejected, with the token counts `ask_events` drops."""
    steps: list[dict[str, Any]] = []
    for event in _run(slug, question, thread_id, client, toolset, checkpointer, None):
        if isinstance(event, Answer):
            return event, steps
        if event.get("kind") == "step_done":
            steps.append(event)
    raise AssertionError("the run ended without an answer")


def ask_events(
    slug: str,
    question: str,
    thread_id: str | None = None,
    *,
    client: anthropic.Anthropic | None = None,
    toolset: Toolset | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    stop: threading.Event | None = None,
) -> Iterator[dict[str, Any]]:
    """The same run as `ask`, as events for the Ask page, in order:
    `start` {thread_id}; per tool call `step` {id, n, tool, input} when Claude asks for it and
    `step_done` {id, n, tool, input, ms, count, error, rows, nodes, rels} when it has run
    (submit_answer is a step without `n`: the answer check); last, `answer` (see `answer_out`).
    Before its steps, each Claude response is an `llm` event {seq, text, thinking, model, stop,
    ms, usage, calls} (`loop.llm_event`); steps carry `call`, the seq of the response that
    asked for them.
    Setting `stop` ends the run at the next step, leaving the thread valid for a follow-up."""
    for event in _run(slug, question, thread_id, client, toolset, checkpointer, stop):
        yield answer_out(event) if isinstance(event, Answer) else event


def run_events(
    slug: str,
    question: str,
    thread_id: str | None = None,
    *,
    client: anthropic.Anthropic | None = None,
    toolset: Toolset | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    stop: threading.Event | None = None,
) -> Iterator[dict[str, Any] | Answer]:
    """`ask_events` with the Answer itself as the last item instead of its `answer` event, for
    a caller that needs what the event leaves out (tokens, nudges): the Ask API, which records
    a trace (`traces.py`) before it sends the answer."""
    yield from _run(slug, question, thread_id, client, toolset, checkpointer, stop)


def answer_out(answer: Answer, trace_id: str | None = None) -> dict[str, Any]:
    """The `answer` event: the Answer without token counts, each source with the step (n) that
    first returned it, and the id of its trace (for a thumbs up or down) when one was kept."""
    return {
        "kind": "answer",
        "trace_id": trace_id,
        "thread_id": answer.thread_id,
        "text": answer.text,
        "sources": [asdict(s) for s in answer.sources],
        "path": [asdict(s) for s in answer.path],
        "stop": answer.stop,
        "model": answer.model,
    }


def _run(slug, question, thread_id, client, toolset, checkpointer, stop) -> Iterator[Any]:
    """Yield the run's step events, then its Answer."""
    thread_id = thread_id or uuid.uuid4().hex[:12]
    graph = build_graph(client or llm.client(), toolset or graph_toolset(), checkpointer)
    company = load_company(slug).name
    first = {
        "role": "user",
        "content": [{"type": "text", "text": f"Company: {company} ({slug})\n\n{question}"}],
    }
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT}
    before = {"usage": 0, "trace": 0}
    if checkpointer is not None:
        # A run that died mid-step (a crash, a server reload) can leave calls without results;
        # the API would reject every later turn of the thread, so answer them first.
        _close_open_tool_calls(graph, config, "Not run: the previous answer ended before it.")
        saved = graph.get_state(config).values
        before = {k: len(saved.get(k, [])) for k in before}
    inputs = {
        "slug": slug,
        "messages": [first],
        "answer": None,
        "stop": None,
        "stop_details": None,
        "nudges": 0,
        "route": None,
    }
    yield {"kind": "start", "thread_id": thread_id}
    numbers: dict[str, int] = {}  # tool_use id -> step number in this answer
    calls: dict[str, int] = {}  # tool_use id -> seq of the Claude response that asked for it
    seq = 0  # Claude responses in this answer
    state: dict[str, Any] = {}
    ended: str | None = None
    try:
        for mode, chunk in graph.stream(inputs, config, stream_mode=["values", "custom"]):
            if mode == "custom":
                if chunk["kind"] == "llm":
                    seq += 1
                    calls.update((c["id"], seq) for c in chunk["calls"])
                    yield {**chunk, "seq": seq}
                    continue
                if chunk["tool"] != SUBMIT:
                    numbers.setdefault(chunk["id"], len(numbers) + 1)
                yield {**chunk, "n": numbers.get(chunk["id"]), "call": calls.get(chunk["id"])}
                continue
            state = chunk
            # Stop only here, after a step is saved: leaving mid-step would drop that step's
            # messages from the checkpoint and break the thread for a follow-up.
            if stop is not None and stop.is_set():
                ended = "stopped"
                break
    except GraphRecursionError:
        ended = "step_limit"
    if ended:
        if checkpointer is not None:
            reason = _NOT_RUN[ended]
            for use in _close_open_tool_calls(graph, config, reason):
                # The page saw this call asked for: tell it the call will never run.
                n = None if use["name"] == SUBMIT else numbers.get(use["id"])
                yield {"kind": "step_done", "id": use["id"], "n": n, "tool": use["name"],
                       "input": use.get("input") or {}, "error": reason,
                       "call": calls.get(use["id"])}  # fmt: skip
            state = graph.get_state(config).values
        state = {**state, "answer": None, "stop": ended}
    elif checkpointer is not None:
        state = graph.get_state(config).values
    trace = (state.get("trace") or [])[before["trace"] :]
    usage = (state.get("usage") or [])[before["usage"] :]
    yield _to_answer(question, thread_id, state, usage, trace)


_NOT_RUN = {
    "step_limit": "Not run: the step limit was reached.",
    "stopped": "Not run: the answer was stopped.",
}


def _close_open_tool_calls(graph, config: dict, reason: str) -> list[dict]:
    """The saved thread may end on tool calls that never ran (step limit, Stop, a run that
    died). Answer them with error results (appended, never edited) so a follow-up in the thread
    stays valid. Returns the calls it closed."""
    messages = graph.get_state(config).values.get("messages") or []
    last = messages[-1] if messages else {}
    uses = [b for b in last.get("content", []) if b.get("type") == "tool_use"]
    if last.get("role") == "assistant" and uses:
        results = [result_block(u["id"], reason, True) for u in uses]
        graph.update_state(
            config, {"messages": [{"role": "user", "content": results}]}, as_node="run_tools"
        )
        return uses
    return []


def _to_answer(
    question: str, thread_id: str, state: dict, usage: list[dict], trace: list[dict]
) -> Answer:
    seen = state.get("seen") or {}
    steps = [t for t in trace if t.get("tool") != SUBMIT]
    # Rows name a node's label and title only sometimes; the steps' subgraphs always do.
    drawn = {n["uid"]: n for t in steps for n in t.get("nodes", ())}

    def source(uid: str) -> Source:
        node = seen.get(uid, {})
        step = next((i for i, t in enumerate(steps, 1) if uid in t.get("uids", ())), None)
        other = drawn.get(uid, {})
        return Source(
            uid=uid,
            title=node.get("title") or other.get("title"),
            url=node.get("url") or other.get("url"),
            label=node.get("label") or other.get("label"),
            step=step,
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
        stop=stop if answer or stop in _KEPT_STOPS else "no_answer",
        stop_details=state.get("stop_details"),
        model=state.get("model"),
        usage=totals,
        nudges=state.get("nudges") or 0,
        thread_messages=len(state.get("messages") or []),
    )
