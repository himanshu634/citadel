"""Agent activity: what the agents did on the graph, one run at a time, for the Systems page.

Why: the Systems page shows where an agent is working now and every step it took, as a trail
over the company map. It needs each step's tool and the brain_<slug> nodes that step touched,
whichever agent ran it. This is that shape, independent of where a run is stored:

- `ActivityRun`: one run of one agent (today an Ask turn; later a Keeper review, whose pm, qa
  and keeper steps fill the same `ActivityStep`s with their own `actor`).
- `ActivityStep`: one tool call, in order, with its input (so the page can say what it did and
  which node it was about) and the uids it touched (so the page can draw it).

Today the only source is the chat history (`agents/history.py`): `runs_from_thread` turns each
Ask turn into a run. Steps that touch nothing on the map (the answer check, MCP calls) keep their
place in the list with no `touched`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from agents.history import Thread

RunStatus = Literal["running", "done", "stopped", "failed"]
StepStatus = Literal["running", "done", "failed"]


class ActivityStep(BaseModel):
    n: int  # 1-based, in the order the agent ran them
    actor: str  # "brain" for Ask; "keeper", "pm", "qa" for a Keeper review
    tool: str
    kind: str = "graph"  # graph, submit, mcp or server (history.Kind)
    input: dict[str, Any] = {}
    status: StepStatus = "done"
    count: int | None = None
    error: str | None = None
    touched: list[str] = []  # brain_<slug> uids, in the order the step returned them


class ActivityRun(BaseModel):
    id: str  # "ask:<thread id>:<turn n>"
    source: Literal["ask"] = "ask"
    actor: str = "brain"
    title: str  # what the run was for: the question
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
