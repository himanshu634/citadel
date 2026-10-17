"""QA agent: tests finished work against the company's past regressions in that system, fails
it with the regression the plan misses, and learns a lesson when a failure repeats
(docs/agents.md, "3. QA agent"). For the Keeper it answers consults on gaps (regression risk, test
evidence), on the Keeper's ledger store."""

from __future__ import annotations

from agents.roles.base import Ctx, Job, Role, Subject, task_context, tasks, write
from agents.roles.keeper import consult_job
from agents.work.store import Row, WorkStore
from agents.work.submits import SubmitQa

LESSON_AFTER = 2  # the same regression failing tasks in one system this often -> a Lesson


def _queue(store: WorkStore, ctx: Ctx) -> list[Subject]:
    rows = store.read("work/queue_qa", {"now": ctx.now})
    return tasks(rows, claim="work/claim_qa", unclaim="work/release_qa")


def _apply(store: WorkStore, ctx: Ctx, s: Subject, sub: SubmitQa) -> list[Row]:
    if sub.verdict == "passed":
        return write(store, ctx, "work/qa_pass", task=s.uid, summary=sub.reason, cites=sub.uids())
    return write(
        store,
        ctx,
        "work/qa_fail",
        task=s.uid,
        last_reason=sub.reason,
        summary=sub.reason,
        cites=sub.uids(),
    )


def _learn(store: WorkStore, ctx: Ctx, s: Subject, sub: SubmitQa, rows: list[Row]) -> None:
    """Procedural memory: after the same regression fails tasks in one system twice, write a
    Lesson to mem_<slug>_qa (QA and developers read it before their next run)."""
    task = store.read("work/get_task", {"task": s.uid})[0]
    if sub.verdict != "failed" or not sub.regression or not task.get("system"):
        return
    hits = store.read("work/qa_failures", {"system": task["system"], "regression": sub.regression})
    if len(hits) < LESSON_AFTER:
        return
    name = task["system"].removeprefix("system:")
    write(
        store,
        ctx,
        "memory/write_lesson",
        system=task["system"],
        regression=sub.regression,
        text=f"{name} changes must cover the case in {sub.regression}: {sub.reason}",
        cites=[sub.regression, *dict.fromkeys(h["task"] for h in hits)],
    )


ROLE = Role(
    name="qa",
    db_user="citadel_qa",
    read_tools=(
        "get_entity",
        "keeper_notes",
        "lessons",
        "past_regressions",
        "related_work_items",
        "task_timeline",
        "work_history",
    ),
    jobs=(Job("test", SubmitQa, _queue, _apply, task_context, after=_learn), consult_job("qa")),
    summary="Tests finished tasks against past regressions; learns lessons from repeats; answers "
    "Keeper consults.",
)
