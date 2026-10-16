"""Builder agent: turns released work into durable Decision nodes, so later agents and people
can ask why something is the way it is (docs/agents.md, "5. Builder agent")."""

from __future__ import annotations

from brain.agents.roles.base import Ctx, Job, Role, Subject, task_context, tasks, write
from brain.work.store import Row, WorkStore
from brain.work.submits import SubmitDecisions


def _queue(store: WorkStore, ctx: Ctx) -> list[Subject]:
    return tasks(store.read("work/queue_builder"))


def _apply(store: WorkStore, ctx: Ctx, s: Subject, sub: SubmitDecisions) -> list[Row]:
    return write(
        store,
        ctx,
        "work/record_decisions",
        task=s.uid,
        decisions=[d.model_dump() for d in sub.decisions],
        summary="; ".join(d.summary for d in sub.decisions),
        cites=sub.uids(),
    )


ROLE = Role(
    name="builder",
    db_user="citadel_builder",
    read_tools=("get_entity", "related_work_items", "task_timeline", "work_history"),
    jobs=(Job("record", SubmitDecisions, _queue, _apply, task_context),),
    summary="Records the decisions made in released tasks as Decision nodes.",
)
