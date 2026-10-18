"""Run one agent job on one subject: think (brain loop), write, log the Episode.

    brain loop: role prompt + role read tools + the job's submit tool
             -> grounding check -> job.apply (named writes) -> Episode (always)

Why: every role decides the same way, so this is the one place that does it. The loop is
`agents/loop.py` (the same one `agents ask` uses), so a role's run follows the same rules:
append-only history, all tool results in one message, and a submit that may cite only uids
seen in tool results this run. `client` is Claude (`llm.client()`) or a scripted policy client
(`agents/policies`); the run can't tell the difference.

A job may bring its own `toolset` (the Archivist's adds its source tools), follow the run as it
goes (`on_event` gets the loop's custom events: `llm`, `step`, `step_done`) and be stopped
(`should_stop`, checked between saved steps: the run ends with stop "stopped" and nothing is
applied).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import anthropic
from langgraph.errors import GraphRecursionError
from langgraph.graph import START, StateGraph
from pydantic import ValidationError

from agents.loop import AgentState, Check, add_brain_loop
from agents.roles.base import Ctx, Job, Role, Subject, write
from agents.toolset import Runner, Toolset
from agents.work.store import Row, WorkStore
from agents.work.submits import Submit

RECURSION_LIMIT = 30  # graph steps per run (each tool round trip is two)
STOPPED = "stopped"  # RunResult.stop when `should_stop` ended the run


@dataclass
class RunResult:
    agent: str
    role: str
    job: str
    subject: str
    rows: list[Row] = field(default_factory=list)  # what the job wrote ([] = nothing)
    submit: dict[str, Any] | None = None  # the accepted submit input
    stop: str | None = None  # why nothing was written: write_refused, no_answer, ...
    tools_called: list[str] = field(default_factory=list)
    submitted: bool = False  # the run called its submit tool (accepted or not)
    episode: str | None = None
    model: str | None = None


# --- tools --------------------------------------------------------------------------------------


def missing_tools(role: Role) -> list[str]:
    """Read tools the role declares that `brain.tools` does not provide."""
    from brain import tools as graph_tools

    return [t for t in role.read_tools if t not in graph_tools.TOOLS]


def role_toolset(role: Role, graph_run: Runner | None = None) -> Toolset:
    """The role's read tools: brain graph tools (`brain.tools`, read-only on brain_<slug>)."""
    from brain import tools as graph_tools

    mapping = {n: graph_tools.TOOLS[n] for n in role.read_tools if n in graph_tools.TOOLS}
    return Toolset(tools=mapping, run=graph_run or graph_tools.call)


# --- grounding ----------------------------------------------------------------------------------


def grounding(submit: type[Submit], subject: Subject) -> Check:
    """The submit's own validation, then ground rule 3: it is about this run's subject, and
    every uid it refers to appeared in a tool result in this run."""

    def check(raw: dict[str, Any], seen: dict[str, Any]) -> str | None:
        try:
            sub = submit.model_validate(raw)
        except ValidationError as e:
            errors = [{"loc": err["loc"], "msg": err["msg"]} for err in e.errors()]
            return f"invalid {submit.name}: {errors}. Fix it and call {submit.name} again."
        if submit.subject and getattr(sub, submit.subject) != subject.uid:
            return f"{submit.subject} must be {subject.uid}, the subject of this run."
        unknown = [u for u in dict.fromkeys(sub.uids()) if u not in seen]
        if unknown:
            return (
                f"These uids did not appear in any tool result: {', '.join(unknown)}. Look "
                f"them up, or remove them, then call {submit.name} again."
            )
        return None

    return check


# --- one run ------------------------------------------------------------------------------------


def context_message(store: WorkStore, role: Role, job: Job, ctx: Ctx, context: dict) -> dict:
    text = (
        f"Company graph: {store.slug}\nYou are {ctx.agent} (role: {role.name}, job: {job.name}).\n"
        f"\n<context>\n{json.dumps(context, indent=1, default=str)}\n</context>\n\n"
        f"Look up what you need, then call {job.submit.name}."
    )
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def run_job(
    store: WorkStore,
    role: Role,
    job: Job,
    subject: Subject,
    ctx: Ctx,
    *,
    client: anthropic.Anthropic,
    graph_run: Runner | None = None,
    toolset: Toolset | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    recursion_limit: int = RECURSION_LIMIT,
) -> RunResult:
    """One run of `job` on `subject`. `toolset` replaces the role's read tools (`graph_run` is
    then unused)."""
    result = RunResult(ctx.agent, role.name, job.name, subject.uid)

    g = StateGraph(AgentState)
    entry = add_brain_loop(
        g,
        client,
        toolset or role_toolset(role, graph_run),
        system_prompt=role.prompt,
        submit_tool=job.submit.tool(),
        check=grounding(job.submit, subject),
    )
    g.add_edge(START, entry)
    message = context_message(store, role, job, ctx, job.context(store, ctx, subject))
    inputs = {
        "slug": store.slug,
        "messages": [message],
        "answer": None,
        "stop": None,
        "stop_details": None,
        "nudges": 0,
    }
    follow = _Follow(on_event, should_stop, recursion_limit)
    try:
        _think_and_write(g, inputs, store, job, subject, ctx, result, follow)
    except Exception as e:  # an API or store failure: log it, carry on
        result.stop = f"error: {type(e).__name__}: {e}"[:300]

    actions = [r["action"] for r in result.rows if "action" in r]
    episode = write(
        store,
        ctx,
        "ledger/write_episode",
        run_at=ctx.now,
        input=f"{role.name}.{job.name} {subject.uid}",
        summary=_summary(result.submit, result.stop),
        tools_called=result.tools_called,
        actions=actions,
        stop=result.stop,
    )
    result.episode = episode[0]["episode"] if episode else None
    return result


@dataclass(frozen=True)
class _Follow:
    on_event: Callable[[dict[str, Any]], None] | None
    should_stop: Callable[[], bool] | None
    recursion_limit: int


def _run_loop(g: StateGraph, inputs: dict[str, Any], follow: _Follow) -> dict[str, Any]:
    """The loop's final state. Followed (`on_event` / `should_stop`), it streams: custom events
    go to `on_event`, and `should_stop` is asked after each saved step while there is no answer
    (a run whose submit was accepted is complete)."""
    config = {"recursion_limit": follow.recursion_limit}
    # No checkpoints, not even a parent's: a job run inside another graph's node (Ask's
    # ask_archivist) must never save into that graph's thread.
    graph = g.compile(checkpointer=False)
    if follow.on_event is None and follow.should_stop is None:
        try:
            return graph.invoke(inputs, config)
        except GraphRecursionError:
            return {"stop": "step_limit"}
    state: dict[str, Any] = {}
    try:
        for mode, chunk in graph.stream(inputs, config, stream_mode=["values", "custom"]):
            if mode == "custom":
                if follow.on_event is not None:
                    follow.on_event(chunk)
                continue
            state = chunk
            if follow.should_stop is not None and not state.get("answer") and follow.should_stop():
                return {**state, "answer": None, "stop": STOPPED}
    except GraphRecursionError:
        return {**state, "answer": None, "stop": "step_limit"}
    return state


def _think_and_write(
    g: StateGraph,
    inputs: dict[str, Any],
    store: WorkStore,
    job: Job,
    subject: Subject,
    ctx: Ctx,
    result: RunResult,
    follow: _Follow,
) -> None:
    """The brain loop, then the job's writes; fills in `result`."""
    state = _run_loop(g, inputs, follow)

    result.model = state.get("model")
    uses = [
        b["name"]
        for m in state.get("messages", [])
        if m["role"] == "assistant"
        for b in m["content"]
        if b.get("type") == "tool_use"
    ]
    result.tools_called = [u for u in uses if u != job.submit.name]
    result.submitted = job.submit.name in uses
    answer = state.get("answer")
    if answer:
        result.submit = answer
        sub = job.submit.model_validate(answer)
        result.rows = job.apply(store, ctx, subject, sub)
        result.stop = None if result.rows else "write_refused"
    else:
        result.stop = state.get("stop") or "no_answer"


def _summary(answer: dict[str, Any] | None, stop: str | None) -> str:
    if not answer:
        return f"No decision ({stop})."
    reason = answer.get("reason")
    if isinstance(reason, str) and reason.strip():
        return reason.strip().splitlines()[0][:300]
    lists = {k: len(v) for k, v in answer.items() if isinstance(v, list) and k != "cites"}
    return ", ".join(f"{n} {k}" for k, n in lists.items()) or "Done."
