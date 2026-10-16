"""Every legal move on a Task, in one table.

Why: ground rule 4 ("one legal move per write"). Each move is one write query,
`queries/work/<name>.cypher`, whose WHERE clause checks exactly the state listed here and whose
SET writes exactly what is listed here. The in-memory store applies this table directly, and
tests pin it, so the Cypher guards have one place to match. A move whose guard fails changes
nothing: "someone else got there first" or "not allowed".

    MOVES["claim_task"].problem(task, role="developer", agent="agent:dev-1", now=100)  # None = ok
    MOVES["claim_task"].changes(task, agent="agent:dev-1", now=100, params={})        # what to SET
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from brain.work.model import ActionKind, Pm, Qa, Status, Task

LEASE_S = 600  # a claim holds the task for this long; the orchestrator expires older ones

# Who must hold the task for the move:
#   any      - nobody in particular
#   assignee - the acting agent is the task's assignee
#   free     - nobody holds it: no assignee, or the assignee's lease ran out
#   expired  - an assignee holds it but the lease ran out (the orchestrator takes it back)
Holder = Literal["any", "assignee", "free", "expired"]


@dataclass(frozen=True)
class Move:
    name: str  # = the write query, queries/work/<name>.cypher
    roles: frozenset[str]  # roles allowed to make it
    action: ActionKind  # the Action kind it logs
    requires: Mapping[str, frozenset[Any]] = field(default_factory=dict)  # field -> allowed now
    needs: tuple[str, ...] = ()  # fields that must be set (not null / not empty)
    holder: Holder = "any"
    sets: Mapping[str, Any] = field(default_factory=dict)  # field -> new value
    takes: tuple[str, ...] = ()  # fields copied from the write's params
    lease: bool = False  # set lease_until = now + LEASE_S (assignee keeps the task)

    def problem(self, task: Task, *, role: str, agent: str, now: int) -> str | None:
        """Why this move is not allowed on `task` right now, or None."""
        if role not in self.roles:
            return f"{role} may not {self.name}"
        for name, allowed in self.requires.items():
            if getattr(task, name) not in allowed:
                return f"{self.name} needs {name} in {sorted(map(str, allowed))}"
        for name in self.needs:
            if not getattr(task, name):
                return f"{self.name} needs {name}"
        held = task.assignee is not None and (task.lease_until or 0) >= now
        if self.holder == "assignee" and task.assignee != agent:
            return f"{self.name} is only for the assignee ({task.assignee})"
        if self.holder == "free" and held:
            return f"{task.uid} is held by {task.assignee}"
        if self.holder == "expired" and (task.assignee is None or held):
            return f"{task.uid} has no expired lease"
        return None

    def changes(self, task: Task, *, agent: str, now: int, params: Mapping[str, Any]) -> dict:
        """The fields this move SETs (static values, taken params, assignee/lease, updated_ts)."""
        out: dict[str, Any] = {**self.sets, "updated_ts": now}
        for name in self.takes:
            out[name] = params.get(name)
        if self.holder == "free":
            out["assignee"] = agent
        if self.lease:
            out["lease_until"] = now + LEASE_S
        return out


def _s(*values: Any) -> frozenset[Any]:
    return frozenset(str(v) if isinstance(v, Status | Qa | Pm) else v for v in values)


PM, DEV, QA, DEVOPS, ORCH = "pm", "developer", "qa", "devops", "orchestrator"
DONE = {"status": _s(Status.DONE)}

MOVES: dict[str, Move] = {
    m.name: m
    for m in [
        # --- PM: triage ---------------------------------------------------------------------
        Move(
            "triage_task",
            frozenset({PM}),
            ActionKind.TRIAGED,
            requires={"status": _s(Status.OPEN)},
            sets={"status": Status.TRIAGED.value},
            takes=("priority", "acceptance", "system"),
        ),
        Move(
            "reject_task",
            frozenset({PM}),
            ActionKind.REJECTED,
            requires={"status": _s(Status.OPEN)},
            sets={"status": Status.REJECTED.value},
            takes=("duplicate_of", "last_reason"),
        ),
        # --- developer ----------------------------------------------------------------------
        Move(
            "claim_task",
            frozenset({DEV}),
            ActionKind.CLAIMED,
            requires={"status": _s(Status.TRIAGED)},
            holder="free",
            sets={"status": Status.IN_PROGRESS.value},
            lease=True,
        ),
        Move(
            "plan_task",
            frozenset({DEV}),
            ActionKind.PLANNED,
            requires={"status": _s(Status.IN_PROGRESS)},
            holder="assignee",
            takes=("plan", "planned_files"),
            lease=True,
        ),
        Move(
            "unclaim_task",
            frozenset({DEV}),
            ActionKind.UNCLAIMED,
            requires={"status": _s(Status.IN_PROGRESS)},
            holder="assignee",
            sets={
                "status": Status.TRIAGED.value,
                "assignee": None,
                "lease_until": None,
                "plan": None,
                "planned_files": [],
            },
            takes=("last_reason",),
        ),
        Move(
            "complete_task",
            frozenset({DEV}),
            ActionKind.COMPLETED,
            requires={"status": _s(Status.IN_PROGRESS)},
            needs=("plan",),
            holder="assignee",
            sets={"status": Status.DONE.value, "qa": Qa.PENDING.value, "pm": Pm.PENDING.value},
            takes=("report",),
        ),
        # --- QA gate ------------------------------------------------------------------------
        Move(
            "claim_qa",
            frozenset({QA}),
            ActionKind.QA_STARTED,
            requires={**DONE, "qa": _s(Qa.PENDING)},
            sets={"qa": Qa.TESTING.value},
        ),
        Move(
            "qa_pass",
            frozenset({QA}),
            ActionKind.QA_PASSED,
            requires={**DONE, "qa": _s(Qa.TESTING)},
            sets={"qa": Qa.PASSED.value},
        ),
        Move(
            "qa_fail",
            frozenset({QA}),
            ActionKind.QA_FAILED,
            requires={**DONE, "qa": _s(Qa.TESTING)},
            sets={"status": Status.IN_PROGRESS.value, "qa": Qa.FAILED.value},
            takes=("last_reason",),
            lease=True,  # back to the same assignee, who keeps it
        ),
        Move(
            "release_qa",
            frozenset({QA}),
            ActionKind.UNCLAIMED,
            requires={**DONE, "qa": _s(Qa.TESTING)},
            sets={"qa": Qa.PENDING.value},
        ),
        # --- PM gate ------------------------------------------------------------------------
        Move(
            "claim_pm",
            frozenset({PM}),
            ActionKind.PM_STARTED,
            requires={**DONE, "pm": _s(Pm.PENDING)},
            sets={"pm": Pm.REVIEWING.value},
        ),
        Move(
            "pm_accept",
            frozenset({PM}),
            ActionKind.PM_ACCEPTED,
            requires={**DONE, "pm": _s(Pm.REVIEWING)},
            sets={"pm": Pm.ACCEPTED.value},
        ),
        Move(
            "pm_changes",
            frozenset({PM}),
            ActionKind.PM_CHANGES_REQUESTED,
            requires={**DONE, "pm": _s(Pm.REVIEWING)},
            sets={"status": Status.IN_PROGRESS.value, "pm": Pm.CHANGES_REQUESTED.value},
            takes=("last_reason",),
            lease=True,
        ),
        Move(
            "release_pm",
            frozenset({PM}),
            ActionKind.UNCLAIMED,
            requires={**DONE, "pm": _s(Pm.REVIEWING)},
            sets={"pm": Pm.PENDING.value},
        ),
        # --- DevOps -------------------------------------------------------------------------
        Move(
            "release_task",
            frozenset({DEVOPS}),
            ActionKind.RELEASED,
            requires={**DONE, "qa": _s(Qa.PASSED), "pm": _s(Pm.ACCEPTED)},
            sets={"status": Status.RELEASED.value},
        ),
        # --- orchestrator -------------------------------------------------------------------
        Move(
            "expire_lease",
            frozenset({ORCH}),
            ActionKind.LEASE_EXPIRED,
            requires={"status": _s(Status.IN_PROGRESS)},
            holder="expired",
            sets={"status": Status.TRIAGED.value, "assignee": None, "lease_until": None},
        ),
    ]
}
