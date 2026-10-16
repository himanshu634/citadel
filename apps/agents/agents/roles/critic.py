"""Critic agent: relates each new decision to the current ones on its systems (supersedes,
contradicts, unrelated); a contradiction opens a task for the PM (docs/agents.md, "6. Critic")."""

from __future__ import annotations

from typing import Any

from agents.roles.base import Ctx, Job, Role, Subject, write
from agents.work.store import Row, WorkStore
from agents.work.submits import SubmitCritique


def _queue(store: WorkStore, ctx: Ctx) -> list[Subject]:
    return [Subject("decision", d["uid"], d) for d in store.read("work/queue_critic")]


def _context(store: WorkStore, ctx: Ctx, s: Subject) -> dict[str, Any]:
    rows = store.read("work/get_decision", {"decision": s.uid})
    d = rows[0] if rows else dict(s.data)
    keep = ("uid", "summary", "rationale", "valid_from", "made_in", "system_uids")
    return {"decision": {k: d.get(k) for k in keep}}


def _apply(store: WorkStore, ctx: Ctx, s: Subject, sub: SubmitCritique) -> list[Row]:
    notes = [f"{r.relation} {r.other}" for r in sub.relations if r.relation != "unrelated"]
    return write(
        store,
        ctx,
        "work/relate_decision",
        decision=s.uid,
        relations=[r.model_dump() for r in sub.relations],
        summary="; ".join(notes) or "No conflicts.",
        cites=sub.uids(),
    )


ROLE = Role(
    name="critic",
    db_user="citadel_critic",
    read_tools=("decisions_as_of", "decisions_for_system", "get_entity"),
    jobs=(Job("check", SubmitCritique, _queue, _apply, _context),),
    summary="Links new decisions to old ones (SUPERSEDES / CONTRADICTS); conflicts become tasks.",
)
