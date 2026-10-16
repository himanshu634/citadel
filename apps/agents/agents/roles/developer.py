"""Developer agent: claims triaged work, plans it from how the codebase really changes, and
reports completion; reworks what a gate sends back (docs/agents.md, "2. Developer agent")."""

from __future__ import annotations

from brain.agents.roles.base import Ctx, Job, Role, Subject, task_context, tasks, write
from brain.work.store import Row, WorkStore
from brain.work.submits import SubmitCompletion, SubmitPlan

UNCLAIM = "work/unclaim_task"


def _own(store: WorkStore, ctx: Ctx) -> list[Row]:
    return store.read("work/queue_dev_own", {"agent": ctx.agent, "now": ctx.now})


def _plan_queue(store: WorkStore, ctx: Ctx) -> list[Subject]:
    """Own tasks with no plan yet, then triaged tasks to claim (atomically, by priority)."""
    mine = tasks([r for r in _own(store, ctx) if not r.get("plan")], unclaim=UNCLAIM)
    free = store.read("work/queue_dev_claimable", {"now": ctx.now})
    return mine + tasks(free, claim="work/claim_task", unclaim=UNCLAIM)


def _complete_queue(store: WorkStore, ctx: Ctx) -> list[Subject]:
    """Own planned tasks; work sent back by QA or the PM comes first."""
    return tasks([r for r in _own(store, ctx) if r.get("plan")])


def _apply_plan(store: WorkStore, ctx: Ctx, s: Subject, sub: SubmitPlan) -> list[Row]:
    if sub.decision == "yield":
        return write(
            store,
            ctx,
            UNCLAIM,
            task=s.uid,
            last_reason=sub.plan,
            summary=f"Yielded: {sub.plan}",
            cites=sub.uids(),
        )
    plan = sub.plan
    if sub.risks:
        plan += "\nRisks: " + "; ".join(sub.risks)
    if sub.consult:
        plan += "\nConsult: " + ", ".join(sub.consult)
    return write(
        store,
        ctx,
        "work/plan_task",
        task=s.uid,
        plan=plan,
        planned_files=sub.planned_files,
        summary=sub.plan,
        cites=sub.uids(),
    )


def _apply_complete(store: WorkStore, ctx: Ctx, s: Subject, sub: SubmitCompletion) -> list[Row]:
    return write(
        store,
        ctx,
        "work/complete_task",
        task=s.uid,
        report=sub.report,
        summary=sub.report.splitlines()[0],
        cites=sub.uids(),
    )


ROLE = Role(
    name="developer",
    db_user="citadel_dev",
    read_tools=(
        "conflicting_tasks",
        "experts_for_system",
        "files_for_system",
        "get_entity",
        "impact_of",
        "lessons",
        "list_systems",
        "task_timeline",
        "work_history",
    ),
    jobs=(
        Job("complete", SubmitCompletion, _complete_queue, _apply_complete, task_context),
        Job("plan", SubmitPlan, _plan_queue, _apply_plan, task_context),
    ),
    summary="Claims triaged tasks, plans them from past changes, reports completion.",
)
