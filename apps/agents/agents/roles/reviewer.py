"""Reviewer-matcher: suggests up to two human reviewers for a finished task, each with the
graph path that justifies them (docs/agents.md, "9. Reviewer-matcher")."""

from __future__ import annotations

from brain.agents.roles.base import Ctx, Job, Role, Subject, task_context, tasks, write
from brain.work.store import Row, WorkStore
from brain.work.submits import SubmitReviewers


def _queue(store: WorkStore, ctx: Ctx) -> list[Subject]:
    return tasks(store.read("work/queue_reviewer", {"now": ctx.now}))


def _apply(store: WorkStore, ctx: Ctx, s: Subject, sub: SubmitReviewers) -> list[Row]:
    return write(
        store,
        ctx,
        "work/suggest_reviewers",
        task=s.uid,
        reviewers=[r.model_dump() for r in sub.reviewers],
        summary=", ".join(r.person for r in sub.reviewers),
        cites=sub.uids(),
    )


ROLE = Role(
    name="reviewer",
    db_user="citadel_reviewer",
    read_tools=("community_of", "experts_for_system", "path_between"),
    jobs=(Job("suggest", SubmitReviewers, _queue, _apply, task_context),),
    summary="Suggests human reviewers for finished tasks, with the path behind each.",
)
