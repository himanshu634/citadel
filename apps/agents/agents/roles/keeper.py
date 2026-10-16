"""Keeper agent: decides each gap under review from the pm and qa consults' answers: a claim,
`needs_person` (nobody could ground it) or `dismiss` (noise). It is the only agent that writes
knowledge (docs/superpowers/specs/2026-10-16-keeper-design.md, "The review run").

Also the consult job pm and qa share: each answers the consults in its own queue with a draft
claim citing uids it saw, or `can_ground: false`. All of these jobs run on the Keeper's ledger
store (`agents.keeper.store`), not the work store.
"""

from __future__ import annotations

from typing import Any

from agents.keeper.model import Gap, log_uid
from agents.roles.base import Ctx, Job, Role, Subject, write
from agents.work.store import Row, WorkStore
from agents.work.submits import SubmitConsult, SubmitKeeperDecision

QUEUE_LIMIT = 100  # gaps in review read per queue pass

_GAP_KEYS = ("uid", "kind", "text", "count", "attempts", "about", "subject")
_ANSWER_KEYS = ("role", "can_ground", "kind", "subject", "statement", "value", "cites")


def log(store: WorkStore, ctx: Ctx, actor: str, action: str, **fields: Any) -> list[Row]:
    """One LogEntry at ctx.now (gap, claim, why, evidence are optional fields)."""
    return write(
        store, ctx, "ledger/log", uid=log_uid(ctx.now), at=ctx.now, actor=actor, action=action,
        **fields,
    )  # fmt: skip


def _gap(store: WorkStore, uid: str) -> dict[str, Any] | None:
    rows = store.read("ledger/get_gap", {"uid": uid})
    return rows[0] if rows else None


def _gap_view(gap: dict[str, Any]) -> dict[str, Any]:
    return {k: gap.get(k) for k in _GAP_KEYS if gap.get(k) not in (None, [], "")}


# --- consult (pm, qa) -------------------------------------------------------------------------


def consult_job(role: str) -> Job:
    """The `consult` job for pm or qa: its open consults, oldest first."""

    def queue(store: WorkStore, ctx: Ctx) -> list[Subject]:
        rows = store.read("ledger/queue_consult", {"role": role})
        return [Subject("consult", c["uid"], c) for c in rows]

    def apply(store: WorkStore, ctx: Ctx, s: Subject, sub: SubmitConsult) -> list[Row]:
        grounded = sub.can_ground
        rows = write(
            store,
            ctx,
            "ledger/answer_consult",
            consult=s.uid,
            can_ground=grounded,
            kind=sub.kind if grounded else None,
            subject=sub.subject_uid if grounded else None,
            statement=sub.statement if grounded else None,
            value=sub.value if grounded else None,
            cites=sub.cites,
        )
        if rows:
            why = sub.statement if grounded else "Could not ground it in the graph."
            log(store, ctx, role, "consult_answered", gap=s.data.get("gap"), why=why,
                evidence=sub.cites)  # fmt: skip
        return rows

    return Job("consult", SubmitConsult, queue, apply, consult_context)


def consult_context(store: WorkStore, ctx: Ctx, s: Subject) -> dict[str, Any]:
    """The consult and the gap it asks about."""
    c = s.data
    gap = _gap(store, c.get("gap", "")) or {"uid": c.get("gap")}
    return {
        "consult": {k: c.get(k) for k in ("uid", "gap", "role", "attempt")},
        "gap": _gap_view(gap),
    }


# --- decide (keeper) --------------------------------------------------------------------------


def queue_decide(store: WorkStore, ctx: Ctx) -> list[Subject]:
    """Gaps in review whose consults (this attempt's) are all answered; at least one."""
    out = []
    for g in store.read("ledger/gaps", {"statuses": ["in_review"], "limit": QUEUE_LIMIT}):
        consults = store.read("ledger/consults_for_gap", {"gap": g["uid"]})
        if consults and all(c["status"] == "answered" for c in consults):
            out.append(Subject("gap", g["uid"], g))
    return out


def decide_context(store: WorkStore, ctx: Ctx, s: Subject) -> dict[str, Any]:
    """The gap and its consults' answers."""
    gap = _gap(store, s.uid) or dict(s.data)
    consults = store.read("ledger/consults_for_gap", {"gap": s.uid})
    return {
        "gap": _gap_view(gap),
        "consults": [{k: c.get(k) for k in _ANSWER_KEYS} for c in consults],
    }


def apply_outcome(store: WorkStore, ctx: Ctx, gap: Gap, sub: SubmitKeeperDecision) -> list[Row]:
    """needs_person or dismiss: the gap leaves review, logged. A claim is Task 8's
    (`keeper.decide.apply_decision` replaces this function)."""
    if sub.outcome == "claim":
        raise NotImplementedError("Task 8: claims are written by keeper.decide.apply_decision")
    to, action = ("needs_person", "needs_person")
    if sub.outcome == "dismiss":
        to, action = ("dismissed", "gap_dismissed")
    rows = write(
        store, ctx, "ledger/set_gap_status", uid=gap.uid, to=to, reason=sub.reason,
        **{"from": ["in_review"]},
    )  # fmt: skip
    if rows:
        log(store, ctx, "keeper", action, gap=gap.uid, why=sub.reason, evidence=sub.cites)
    return rows


def apply_decide(store: WorkStore, ctx: Ctx, s: Subject, sub: SubmitKeeperDecision) -> list[Row]:
    gap = _gap(store, s.uid)
    return apply_outcome(store, ctx, Gap(**(gap or s.data)), sub)


ROLE = Role(
    name="keeper",
    db_user="citadel_keeper",
    read_tools=(
        "experts_for_system",
        "get_entity",
        "keeper_notes",
        "owners_vs_experts",
        "person_profile",
        "related_documents",
        "related_work_items",
        "work_history",
    ),
    jobs=(Job("decide", SubmitKeeperDecision, queue_decide, apply_decide, decide_context),),
    summary="Decides gaps from the pm and qa consults: a claim, needs_person or dismiss.",
)
