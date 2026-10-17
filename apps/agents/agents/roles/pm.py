"""PM agent: for the Keeper it answers consults on gaps and opens a follow-up task for each claim
that needs one (an accepted owner, expert or decision claim, or a claim that conflicts with a
source). Both jobs run on the Keeper's ledger store (docs/agents.md, "The Keeper")."""

from __future__ import annotations

from typing import Any

from agents.roles.base import Ctx, Job, Role, Subject, write
from agents.roles.keeper import consult_job, log
from agents.work.store import Row, WorkStore
from agents.work.submits import SubmitFollowUp


def _follow_up_queue(store: WorkStore, ctx: Ctx) -> list[Subject]:
    return [Subject("claim", c["uid"], c) for c in store.read("ledger/queue_follow_up", {})]


def _follow_up_context(store: WorkStore, ctx: Ctx, s: Subject) -> dict[str, Any]:
    rows = store.read("ledger/get_claim", {"uid": s.uid})
    c = rows[0] if rows else dict(s.data)
    keep = ("uid", "kind", "subject", "statement", "value", "status", "conflict", "about",
            "evidence")  # fmt: skip
    return {"claim": {k: c.get(k) for k in keep if c.get(k) not in (None, [], "")}}


def _apply_follow_up(store: WorkStore, ctx: Ctx, s: Subject, sub: SubmitFollowUp) -> list[Row]:
    rows = write(
        store, ctx, "ledger/open_followup", claim=s.uid, title=sub.title, body=sub.body, by="pm"
    )
    if not rows or not rows[0].get("created"):
        return []  # one follow-up per claim: someone opened it already
    log(store, ctx, "pm", "follow_up_opened", claim=s.uid, why=sub.title, evidence=sub.cites)
    return rows


ROLE = Role(
    name="pm",
    db_user="citadel_pm",
    read_tools=(
        "get_entity",
        "keeper_notes",
        "list_systems",
        "related_work_items",
        "work_history",
    ),
    jobs=(
        consult_job("pm"),
        Job("follow_up", SubmitFollowUp, _follow_up_queue, _apply_follow_up, _follow_up_context),
    ),
    summary="Answers Keeper consults and opens follow-ups for its claims.",
)
