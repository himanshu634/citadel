"""PM agent: seeds tasks from issues and risk findings, triages them, and later accepts or sends
back finished work against the acceptance criteria it wrote (docs/agents.md, "1. PM agent").

For the Keeper it answers consults on gaps and opens a follow-up task for each claim that needs
one (an accepted owner, expert or decision claim, or a claim that conflicts with a source); those
two jobs run on the Keeper's ledger store."""

from __future__ import annotations

from typing import Any

from agents.roles.base import Ctx, Job, Role, Subject, task_context, tasks, write
from agents.roles.keeper import consult_job, log
from agents.work.store import Row, WorkStore
from agents.work.submits import SubmitAcceptance, SubmitFollowUp, SubmitTriage


def intake(store: WorkStore, ctx: Ctx) -> list[Row]:
    """Seed one task per open issue and per risk finding that has none yet. Mechanical, so no
    LLM: the decision is in triage."""
    out: list[Row] = []
    for issue in store.read("work/untasked_issues", db_user=ctx.db_user):
        out += write(
            store,
            ctx,
            "work/seed_task",
            title=issue["title"],
            body=issue.get("body") or "",
            from_issue=issue["uid"],
            mentions=issue.get("mentions", 0),
        )
    for f in store.read("work/untasked_findings", db_user=ctx.db_user):
        out += write(
            store,
            ctx,
            "work/seed_task",
            title=f"Risk ({f['kind']}): {f['summary']}",
            body=f"Finding {f['uid']} about {f['subject']}. Cites: {', '.join(f['cites'])}",
            from_finding=f["uid"],
            cites=f["cites"],
        )
    return out


def _triage_queue(store: WorkStore, ctx: Ctx) -> list[Subject]:
    return tasks(store.read("work/queue_pm_triage", {"now": ctx.now}))


def _apply_triage(store: WorkStore, ctx: Ctx, s: Subject, sub: SubmitTriage) -> list[Row]:
    if sub.decision == "triage":
        return write(
            store,
            ctx,
            "work/triage_task",
            task=s.uid,
            priority=sub.priority,
            acceptance=sub.acceptance,
            system=sub.system,
            summary=sub.reason,
            cites=sub.uids(),
        )
    return write(
        store,
        ctx,
        "work/reject_task",
        task=s.uid,
        duplicate_of=sub.duplicate_of,
        last_reason=sub.reason,
        summary=sub.reason,
        cites=sub.uids(),
    )


def _accept_queue(store: WorkStore, ctx: Ctx) -> list[Subject]:
    rows = store.read("work/queue_pm_accept", {"now": ctx.now})
    return tasks(rows, claim="work/claim_pm", unclaim="work/release_pm")


def _apply_accept(store: WorkStore, ctx: Ctx, s: Subject, sub: SubmitAcceptance) -> list[Row]:
    if sub.verdict == "accepted":
        return write(store, ctx, "work/pm_accept", task=s.uid, summary=sub.reason, cites=sub.uids())
    return write(
        store,
        ctx,
        "work/pm_changes",
        task=s.uid,
        last_reason=sub.reason,
        summary=sub.reason,
        cites=sub.uids(),
    )


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
        "semantic_similar_tasks",
        "similar_tasks",
        "task_timeline",
        "work_history",
    ),
    jobs=(
        Job("triage", SubmitTriage, _triage_queue, _apply_triage, task_context),
        Job("accept", SubmitAcceptance, _accept_queue, _apply_accept, task_context),
        consult_job("pm"),
        Job("follow_up", SubmitFollowUp, _follow_up_queue, _apply_follow_up, _follow_up_context),
    ),
    summary="Seeds and triages tasks; accepts finished work; answers Keeper consults and opens "
    "follow-ups for its claims.",
)
