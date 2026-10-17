"""Run one agent job on one subject: claim, think (brain loop), write, log the Episode.

    claim (atomic write) -> brain loop: role prompt + role read tools + the job's submit tool
                         -> grounding check -> job.apply (named writes) -> job.after
                         -> Episode (always, once claimed)

Why: every role decides the same way, so this is the one place that does it. The loop is
`agents/loop.py` (the same one `agents ask` uses), so a role's run follows the same rules:
append-only history, all tool results in one message, and a submit that may cite only uids
seen in tool results this run. `client` is Claude (`llm.client()`) or a scripted policy client
(`agents/policies`); the run can't tell the difference.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import anthropic
from brain.config import graph_name
from langgraph.errors import GraphRecursionError
from langgraph.graph import START, StateGraph
from pydantic import BaseModel, ValidationError

from agents import acl
from agents.loop import AgentState, Check, add_brain_loop
from agents.roles.base import Ctx, Job, Role, Subject, write
from agents.toolset import Runner, Toolset
from agents.work.store import Row, WorkStore
from agents.work.submits import Submit
from agents.work.tools import WORK_TOOLS

RECURSION_LIMIT = 30  # graph steps per run (each tool round trip is two)


@dataclass
class RunResult:
    agent: str
    role: str
    job: str
    subject: str
    rows: list[Row] = field(default_factory=list)  # what the job wrote ([] = nothing)
    submit: dict[str, Any] | None = None  # the accepted submit input
    stop: str | None = None  # why nothing was written: claim_lost, write_refused, no_answer, ...
    tools_called: list[str] = field(default_factory=list)
    episode: str | None = None
    model: str | None = None


# --- tools --------------------------------------------------------------------------------------


def available_tools() -> set[str]:
    from brain import tools as graph_tools

    return {*graph_tools.TOOLS, *WORK_TOOLS}


def missing_tools(role: Role) -> list[str]:
    """Read tools the role declares that no store or graph query provides yet (phase 2)."""
    return [t for t in role.read_tools if t not in available_tools()]


def role_toolset(
    role: Role, store: WorkStore, db_user: str, graph_run: Runner | None = None
) -> Toolset:
    """The role's read tools: brain graph tools (`brain.tools`, read-only on brain_<slug>) and
    work-layer tools (run by the store, as the role's own database user)."""
    from brain import tools as graph_tools

    run_graph = graph_run or graph_tools.call
    mapping: dict[str, Any] = {}
    for name in role.read_tools:
        tool = WORK_TOOLS.get(name) or graph_tools.TOOLS.get(name)
        if tool is not None:
            mapping[name] = tool

    def run(slug: str, name: str, **params: Any) -> list[BaseModel]:
        work = WORK_TOOLS.get(name)
        if work is None:
            return run_graph(slug, name, **params)
        rows = store.read(work.query, params, db_user=db_user)
        return [work.row.model_validate(r) for r in rows]

    return Toolset(tools=mapping, run=run)


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
) -> RunResult:
    result = RunResult(ctx.agent, role.name, job.name, subject.uid)
    if subject.claim and not write(
        store, ctx, subject.claim, task=subject.uid, summary=f"{ctx.agent} took {subject.uid}"
    ):
        result.stop = "claim_lost"  # someone else got there first: not a run
        return result

    g = StateGraph(AgentState)
    entry = add_brain_loop(
        g,
        client,
        role_toolset(role, store, ctx.db_user, graph_run),
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
    try:
        _think_and_write(g, inputs, store, job, subject, ctx, result)
    except Exception as e:  # an API or store failure: give the work back, log it, carry on
        result.stop = f"error: {type(e).__name__}: {e}"[:300]
    if not result.rows and subject.unclaim:  # give the work back for someone else
        write(
            store,
            ctx,
            subject.unclaim,
            task=subject.uid,
            summary=f"{ctx.agent} gave {subject.uid} back ({result.stop})",
        )

    actions = [r["action"] for r in result.rows if "action" in r]
    # A read-only role (Risk) cannot write the brain; it logs its runs in its own memory graph.
    own = acl.can(ctx.db_user, store.slug, graph_name(store.slug), "W")
    episode = write(
        store,
        ctx,
        "work/write_episode" if own else "memory/write_episode",
        run_at=ctx.now,
        tick=ctx.tick,
        input=f"{role.name}.{job.name} {subject.uid}",
        summary=_summary(result.submit, result.stop),
        tools_called=result.tools_called,
        actions=actions,
        stop=result.stop,
    )
    result.episode = episode[0]["episode"] if episode else None
    return result


def _think_and_write(
    g: StateGraph,
    inputs: dict[str, Any],
    store: WorkStore,
    job: Job,
    subject: Subject,
    ctx: Ctx,
    result: RunResult,
) -> None:
    """The brain loop, then the job's writes; fills in `result`."""
    try:
        state = g.compile().invoke(inputs, {"recursion_limit": RECURSION_LIMIT})
    except GraphRecursionError:
        state = {"stop": "step_limit"}

    result.model = state.get("model")
    result.tools_called = [
        b["name"]
        for m in state.get("messages", [])
        if m["role"] == "assistant"
        for b in m["content"]
        if b.get("type") == "tool_use" and b["name"] != job.submit.name
    ]
    answer = state.get("answer")
    if answer:
        result.submit = answer
        sub = job.submit.model_validate(answer)
        result.rows = job.apply(store, ctx, subject, sub)
        if result.rows and job.after:
            job.after(store, ctx, subject, sub, result.rows)
        result.stop = None if result.rows else "write_refused"
    else:
        result.stop = state.get("stop") or "no_answer"


def _summary(answer: dict[str, Any] | None, stop: str | None) -> str:
    if not answer:
        return f"No decision ({stop})."
    for key in ("reason", "plan", "report", "notes"):
        if isinstance(answer.get(key), str) and answer[key].strip():
            return answer[key].strip().splitlines()[0][:300]
    lists = {k: len(v) for k, v in answer.items() if isinstance(v, list) and k != "cites"}
    return ", ".join(f"{n} {k}" for k, n in lists.items()) or "Done."
