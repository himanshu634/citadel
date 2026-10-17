"""The contract every agent role implements (docs/agents.md, "The agent contract").

A role is a FalkorDB user, a prompt, a sorted list of read tools, and its jobs. A job is one kind
of decision: where its work comes from (a named queue read), the one submit tool it ends with,
and how that submit becomes named writes. The
runner (`agents/runner.py`) does the rest the same way for every job, through the brain loop.

    role = ROLES["qa"]
    job = role.job("consult")
    for subject in job.queue(store, ctx): ...      # its open consults, oldest first
    job.apply(store, ctx, subject, submit)         # -> rows written ([] = guard did not match)
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

from agents.work.store import Row, WorkStore
from agents.work.submits import Submit


@dataclass(frozen=True)
class Ctx:
    """Who is acting, and when."""

    agent: str  # agent uid, e.g. agent:dev-1
    db_user: str
    now: int


@dataclass(frozen=True)
class Subject:
    """What one run is about: a consult, a gap or a claim."""

    kind: str
    uid: str
    data: Mapping[str, Any] = field(default_factory=dict)  # the queue row


Queue = Callable[[WorkStore, Ctx], list[Subject]]
Apply = Callable[[WorkStore, Ctx, Subject, Submit], list[Row]]
Context = Callable[[WorkStore, Ctx, Subject], dict[str, Any]]


@dataclass(frozen=True)
class Job:
    name: str  # e.g. "consult"
    submit: type[Submit]
    queue: Queue
    apply: Apply
    context: Context  # what the run is told up front (the subject and anything it needs)


@dataclass(frozen=True)
class Role:
    name: str  # e.g. "qa"
    db_user: str  # the FalkorDB user it connects as (acl.PERMISSIONS)
    read_tools: tuple[str, ...]  # sorted; names from brain.tools.TOOLS
    jobs: tuple[Job, ...]
    summary: str = ""  # one line for `agents agents`

    @property
    def prompt(self) -> str:
        """Shared rules + the role's own prompt; static, so the request prefix caches."""
        files = resources.files("agents").joinpath("prompts")
        shared = files.joinpath("_shared.md").read_text()
        return f"{shared}\n\n{files.joinpath(f'{self.name}.md').read_text()}"

    def job(self, name: str) -> Job:
        return next(j for j in self.jobs if j.name == name)


def write(store: WorkStore, ctx: Ctx, name: str, **params: Any) -> list[Row]:
    """A named write as this agent, with the standard agent/now params."""
    return store.write(name, ctx.db_user, {"agent": ctx.agent, "now": ctx.now, **params})
