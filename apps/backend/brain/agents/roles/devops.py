"""DevOps / release agent: ships accepted work in trains that share no systems, holds a risky
train for one tick, and notifies the people a release touches (docs/agents.md, "4. DevOps")."""

from __future__ import annotations

from typing import Any

from brain.agents.roles.base import Ctx, Job, Role, Subject, write
from brain.work.store import Row, WorkStore
from brain.work.submits import SubmitRelease


def _queue(store: WorkStore, ctx: Ctx) -> list[Subject]:
    """Label newly accepted tasks :ReleaseCandidate, then one subject per release train."""
    write(store, ctx, "work/mark_release_candidates")
    return [Subject("train", t["uid"], t) for t in store.read("tools/release_trains")]


def _context(store: WorkStore, ctx: Ctx, s: Subject) -> dict[str, Any]:
    titles = []
    for uid in s.data["task_uids"]:
        task = store.read("work/get_task", {"task": uid})[0]
        titles.append({"uid": uid, "title": task["title"], "system": task.get("system")})
    return {"train": {**s.data, "tasks": titles}}


def _apply(store: WorkStore, ctx: Ctx, s: Subject, sub: SubmitRelease) -> list[Row]:
    if sub.decision == "hold":
        return write(
            store, ctx, "work/hold_train", train=s.uid, summary=sub.notes, cites=sub.uids()
        )
    return write(
        store,
        ctx,
        "work/create_release",
        train=s.uid,
        release_name=sub.release_name,
        notes=sub.notes,
        impacts=[i.model_dump() for i in sub.impacts],
        notify=sub.notify,
        cites=sub.uids(),
    )


ROLE = Role(
    name="devops",
    db_user="citadel_devops",
    read_tools=(
        "blast_radius",
        "experts_for_system",
        "list_systems",
        "release_trains",
        "task_timeline",
    ),
    jobs=(Job("release", SubmitRelease, _queue, _apply, _context),),
    summary="Ships accepted tasks in independent release trains and notifies who they touch.",
)
