"""Agent activity: what the agents did on the graph, one run at a time, for the Systems page.

Why: the Systems page shows where an agent is working now and every step it took, as a trail
over the company map. It needs each step's tool and the brain_<slug> nodes that step touched,
whichever agent ran it. This is that shape, independent of where a run is stored:

- `ActivityRun`: one run of one agent: an Ask turn, or a Keeper review, whose pm, qa and keeper
  steps fill the same `ActivityStep`s with their own `actor`.
- `ActivityStep`: one tool call, in order, with its input (so the page can say what it did and
  which node it was about) and the uids it touched (so the page can draw it).

Three sources: the chat history (`agents/history.py`), where `runs_from_thread` turns each Ask turn
into a run, and the Keeper's ledger (`keeper/review.py` writes each review's steps), where
`runs_from_reviews` turns each review into one and `runs_from_archive` each Archivist request
(its steps hang off the request's uid). Steps that touch nothing on the map (the answer
check, a job's submit, MCP calls) keep their place in the list with no `touched`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from agents.history import Thread
from agents.keeper.model import ArchiveRequest, Review, ReviewStep

RunStatus = Literal["running", "done", "stopped", "failed"]
StepStatus = Literal["running", "done", "failed"]


class ActivityStep(BaseModel):
    n: int  # 1-based, in the order the agent ran them
    actor: str  # "brain" for Ask; "keeper", "pm", "qa" for a Keeper review; "archivist"
    tool: str
    kind: str = "graph"  # graph, submit, mcp or server (history.Kind)
    input: dict[str, Any] = {}
    status: StepStatus = "done"
    count: int | None = None
    error: str | None = None
    touched: list[str] = []  # brain_<slug> uids, in the order the step returned them


class ActivityRun(BaseModel):
    id: str  # "ask:<thread id>:<turn n>", "keeper:<review uid>" or "archive:<request uid>"
    source: Literal["ask", "keeper", "archive"] = "ask"
    actor: str = "brain"
    title: str  # what the run was for: the question, or the review's first gap
    status: RunStatus
    started_at: datetime
    ended_at: datetime | None = None
    thread_id: str | None = None  # an Ask run reopens in its chat
    steps: list[ActivityStep] = []


class Activity(BaseModel):
    runs: list[ActivityRun]  # newest first
    running: bool  # some run is still going, so the page keeps watching


def _status(step_status: str, error: str | None) -> StepStatus:
    if step_status == "running":
        return "running"
    return "failed" if error else "done"


def runs_from_thread(thread: Thread) -> list[ActivityRun]:
    """One run per turn of an Ask chat, oldest turn first."""
    runs = []
    for turn in thread.turns:
        steps = [
            ActivityStep(
                n=i,
                actor="brain",
                tool=s.tool,
                kind=s.kind,
                input=s.input or {},
                status=_status(s.status, s.error),
                count=s.count,
                error=s.error,
                touched=list(dict.fromkeys(n["uid"] for n in s.nodes if n.get("uid"))),
            )
            for i, s in enumerate(turn.steps, start=1)
        ]
        runs.append(
            ActivityRun(
                id=f"ask:{thread.id}:{turn.n}",
                title=turn.question,
                status=turn.status,
                started_at=turn.started_at,
                ended_at=turn.ended_at,
                thread_id=thread.id,
                steps=steps,
            )
        )
    return runs


TRIGGER_TITLES = {
    "build": "Keeper review after a build",
    "manual": "Keeper review on request",
    "approval": "Keeper review after an approval",
    "archive": "Keeper review after the Archivist found history",
}
_REVIEW_STATUS: dict[str, RunStatus] = {
    "done": "done",
    "stopped": "stopped",
    "failed": "failed",
    "skipped": "done",
}


def _review_title(review: Review) -> str:
    if not review.gaps:
        return TRIGGER_TITLES[review.trigger]
    first = review.gap_text or review.gaps[0]
    more = len(review.gaps) - 1
    return f"{first} (+{more} more)" if more else first


def runs_from_reviews(
    reviews: list[Review],
    steps_by_review: Mapping[str, list[ReviewStep]],
    *,
    live: Callable[[str], bool],
) -> list[ActivityRun]:
    """One run per Keeper review, in the order given. A `running` review stays running only
    when `live(uid)` (this process runs it); else no run can finish it, so it is `stopped` and
    its running steps `failed` ("interrupted"). A skipped review is `done`; one with no steps
    did nothing to show and is left out."""
    runs = []
    for review in reviews:
        steps = sorted(steps_by_review.get(review.uid, []), key=lambda s: s.n)
        if review.state == "skipped" and not steps:
            continue
        if review.state == "running":
            status: RunStatus = "running" if live(review.uid) else "stopped"
        else:
            status = _REVIEW_STATUS[review.state]
        lost = status != "running"
        runs.append(
            ActivityRun(
                id=f"keeper:{review.uid}",
                source="keeper",
                actor="keeper",
                title=_review_title(review),
                status=status,
                started_at=review.started_at,  # type: ignore[arg-type]  # ISO text, parsed
                ended_at=review.ended_at,  # type: ignore[arg-type]
                steps=[
                    ActivityStep(
                        n=s.n,
                        actor=s.actor,
                        tool=s.tool,
                        kind=s.kind,
                        input=s.input,
                        status="failed" if lost and s.status == "running" else s.status,
                        count=s.count,
                        error="interrupted" if lost and s.status == "running" else s.error,
                        touched=list(dict.fromkeys(s.touched)),
                    )
                    for s in steps
                ],
            )
        )
    return runs


def _step(s: ReviewStep, lost: bool) -> ActivityStep:
    return ActivityStep(
        n=s.n,
        actor=s.actor,
        tool=s.tool,
        kind=s.kind,
        input=s.input,
        status="failed" if lost and s.status == "running" else s.status,
        count=s.count,
        error="interrupted" if lost and s.status == "running" else s.error,
        touched=list(dict.fromkeys(s.touched)),
    )


def runs_from_archive(
    requests: list[ArchiveRequest],
    steps_by_request: Mapping[str, list[ReviewStep]],
    *,
    live: Callable[[ArchiveRequest], bool],
) -> list[ActivityRun]:
    """One run per Archivist request, in the order given. An `open` or `running` request stays
    running only when `live(request)` (this process runs it); else it is `stopped`. A request
    with no steps (open and waiting, refused, or answered from memory) did nothing to show and
    is left out."""
    runs = []
    for req in requests:
        steps = sorted(steps_by_request.get(req.uid, []), key=lambda s: s.n)
        if not steps:
            continue
        if req.status in ("open", "running"):
            status: RunStatus = "running" if live(req) else "stopped"
        else:
            status = "failed" if req.status == "failed" else "done"
        runs.append(
            ActivityRun(
                id=f"archive:{req.uid}",
                source="archive",
                actor="archivist",
                title=f"Archivist: {req.text}",
                status=status,
                started_at=req.created_at,  # type: ignore[arg-type]  # ISO text, parsed
                ended_at=None if status == "running" else req.updated_at,  # type: ignore[arg-type]
                thread_id=req.thread,
                steps=[_step(s, status != "running") for s in steps],
            )
        )
    return runs
