"""The contract every agent role implements (docs/agents.md, "The agent contract").

A role is a FalkorDB user, a prompt, a sorted list of read tools, and one or more jobs. A job is
one kind of decision: where its work comes from (a named queue read), how it claims a subject
atomically, the one submit tool it ends with, and how that submit becomes named writes. The
runner (`agents/runner.py`) does the rest the same way for every job, through the brain loop.

    role = ROLES["qa"]
    job = role.jobs[0]
    for subject in job.queue(store, ctx): ...      # ordered by citadel priority
    job.apply(store, ctx, subject, submit)         # -> rows written ([] = guard did not match)
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

from brain.work.store import Row, WorkStore
from brain.work.submits import Submit


@dataclass(frozen=True)
class Ctx:
    """Who is acting, and when."""

    agent: str  # agent uid, e.g. agent:dev-1
    db_user: str
    now: int
    tick: int = 0


@dataclass(frozen=True)
class Subject:
    """What one run is about: a task, a decision, a release train or a risk scan."""

    kind: str
    uid: str
    data: Mapping[str, Any] = field(default_factory=dict)  # the queue row
    claim: str | None = None  # write that claims it atomically before the run, if any
    unclaim: str | None = None  # write that gives the claim back if the run writes nothing


Queue = Callable[[WorkStore, Ctx], list[Subject]]
Apply = Callable[[WorkStore, Ctx, Subject, Submit], list[Row]]
Context = Callable[[WorkStore, Ctx, Subject], dict[str, Any]]
After = Callable[[WorkStore, Ctx, Subject, Submit, list[Row]], None]


@dataclass(frozen=True)
class Job:
    name: str  # e.g. "triage"
    submit: type[Submit]
    queue: Queue
    apply: Apply
    context: Context  # what the run is told up front (the subject and anything it needs)
    after: After | None = None  # deterministic follow-up after a successful write


@dataclass(frozen=True)
class Role:
    name: str  # e.g. "qa"
    db_user: str  # the FalkorDB user it connects as (acl.PERMISSIONS)
    read_tools: tuple[str, ...]  # sorted; names from brain.tools.TOOLS or work.tools.WORK_TOOLS
    jobs: tuple[Job, ...]  # tried in order; an agent does at most one per tick
    every: int = 1  # runs on ticks where tick % every == 0
    summary: str = ""  # one line for `brain agents`

    @property
    def prompt(self) -> str:
        """Shared rules + the role's own prompt; static, so the request prefix caches."""
        files = resources.files("brain.agents").joinpath("prompts")
        shared = files.joinpath("_shared.md").read_text()
        return f"{shared}\n\n{files.joinpath(f'{self.name}.md').read_text()}"

    def job(self, name: str) -> Job:
        return next(j for j in self.jobs if j.name == name)


def write(store: WorkStore, ctx: Ctx, name: str, **params: Any) -> list[Row]:
    """A named write as this agent, with the standard agent/now params."""
    return store.write(name, ctx.db_user, {"agent": ctx.agent, "now": ctx.now, **params})


def tasks(
    rows: list[Row], *, claim: str | None = None, unclaim: str | None = None
) -> list[Subject]:
    return [Subject("task", r["uid"], r, claim, unclaim) for r in rows]


def task_context(store: WorkStore, ctx: Ctx, subject: Subject) -> dict[str, Any]:
    """The task as it is now (after any claim), with its system's name."""
    rows = store.read("work/get_task", {"task": subject.uid})
    task = rows[0] if rows else dict(subject.data)
    keep = (
        "uid",
        "title",
        "body",
        "status",
        "priority",
        "qa",
        "pm",
        "acceptance",
        "plan",
        "planned_files",
        "report",
        "system",
        "last_reason",
        "duplicate_of",
        "created_ts",
    )
    out = {k: task.get(k) for k in keep if task.get(k) not in (None, [], "")}
    if task.get("system"):
        out["system_name"] = task["system"].removeprefix("system:")
    return {"task": out}
