"""The Keeper's decide step, in code: what a decision, an approval or a rejection writes.

Why: the model only proposes. Whether a claim becomes knowledge is fixed here, in this order
(docs/superpowers/specs/2026-10-16-keeper-design.md, "The review run" steps 4-5):

1. `dismiss` / `needs_person`: the gap leaves review. `ask_archivist` (`_ask_archivist`): the
   gap waits (`waiting_archive`) while the review's archive step runs the request it opens; a
   gap asks once, ever, so a second ask is `needs_person`.
2. Evidence: every cited uid must be a node in brain_<slug>, else the claim is `rejected`
   (`evidence_missing`) and the gap goes back to `open` with one more attempt (`needs_person` at
   `MAX_ATTEMPTS`).
3. Sources win: a claim the sources contradict is `conflicts_with_source`, never projected, and
   skips approval; the gap is resolved (pm's follow-up fixes the source).
4. Critical rule: a critical claim waits for a lead (`pending_approval`, the gap stays
   `in_review`); any other is accepted at once (`accept`).

`accept` projects the claim into the brain, then supersedes the accepted claim of the same kind
and subject; when projection finds its subject or evidence gone it is `stale` instead (its gap
reopens with one more attempt, `needs_person` at `MAX_ATTEMPTS`, as after a rejection; the
earlier claim stays). Re-projection after a build (`project.py`) marks stale without an
attempt. `approve` re-checks the sources first, since they may have changed while the claim
waited. A missing brain_<slug> (a rebuild) raises `BrainUnavailable`
before any write an empty brain would make wrong.

Every claim status move is guarded on its current status, so of two racing approvals (or approve
and reject) one wins and the other raises `ClaimNotPending` having written nothing. Every path
writes exactly one LogEntry for its outcome (plus one `claim_superseded` per claim it replaces):

    decide:  gap_dismissed | needs_person | archive_requested | claim_rejected
             | claim_conflicts_with_source | claim_queued | claim_written (actor "auto")
             | claim_stale
    approve: claim_approved | claim_conflicts_with_source | claim_stale
             | claim_approval_failed (the projection failed)  (actor: the lead)
    reject:  claim_rejected  (actor: the lead)
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Protocol

from brain import db
from brain import keeper as brain_keeper
from brain.keeper import SourceFacts

from agents.archivist.rules import norm
from agents.keeper.model import Claim, Gap, archive_uid, claim_uid, iso, log_uid
from agents.keeper.rules import conflict, critical_reasons
from agents.work.store import Row, WorkStore

if TYPE_CHECKING:
    from agents.roles.base import Ctx
    from agents.work.submits import SubmitKeeperDecision

DB_USER = "citadel_keeper"  # the Keeper's database user (roles/keeper.py ROLE.db_user)
# Why a review or a lead's decision is refused while the company builds: a rebuild drops
# brain_<slug> and makes it again, empty, so every claim would look stale or ungrounded.
BUILDING = "The brain is being rebuilt; try again when the build finishes."
MAX_ATTEMPTS = 2  # rejected claims before a gap needs a person
ALREADY_ASKED = "already asked the Archivist"  # a gap asks the Archivist once, ever
EARLIER_LIMIT = 10_000  # accepted claims read for the critical rule's replaces_claim


class ClaimNotPending(Exception):
    """The claim is not (or no longer) waiting for approval: someone else decided it first."""


class BrainUnavailable(Exception):
    """brain_<slug> does not exist (a rebuild deleted it). Raised before any write that an
    empty brain would make wrong: rejecting for missing evidence, marking stale, superseding.
    The review run stops on it (`stop="brain_unavailable"`)."""


class BrainFacts(Protocol):
    """What the decide step reads from and writes to brain_<slug> (`brain.keeper`)."""

    def evidence(self, slug: str, uids: list[str]) -> dict[str, str]: ...

    def source_facts(self, slug: str, subject: str) -> SourceFacts: ...

    def high_impact_systems(self, slug: str) -> set[str]: ...

    def project(self, slug: str, claims: list[dict[str, Any]]) -> list[str]: ...

    def retire(self, slug: str, uid: str, status: str, valid_to: str) -> None: ...

    def graph_exists(self, slug: str) -> bool: ...


class _Brain:
    """The real brain facts: `brain.keeper`, and `brain.db.graph_exists`. `notice` is for the
    review run (`keeper/review.py`), which shares this default."""

    evidence = staticmethod(brain_keeper.evidence)
    source_facts = staticmethod(brain_keeper.source_facts)
    high_impact_systems = staticmethod(brain_keeper.high_impact_systems)
    project = staticmethod(brain_keeper.project)
    retire = staticmethod(brain_keeper.retire)
    graph_exists = staticmethod(db.graph_exists)
    notice = staticmethod(brain_keeper.notice)


# Read at call time, so tests and offline runs can swap it (a job's apply has no brain argument).
DEFAULT_BRAIN: BrainFacts = _Brain()


# --- decide ----------------------------------------------------------------------------------


def apply_decision(
    store: WorkStore,
    ctx: Ctx,
    gap: Gap,
    sub: SubmitKeeperDecision,
    brain: BrainFacts | None = None,
) -> list[Row]:
    """Write the Keeper's decision on a gap in review. [] when the gap is no longer in review
    (nothing written). Rows: the gap's new status, or the claim's final status."""
    if sub.outcome == "ask_archivist":
        return _ask_archivist(store, ctx, gap, sub)
    if sub.outcome != "claim":
        to, action = ("dismissed", "gap_dismissed") if sub.outcome == "dismiss" else (
            "needs_person", "needs_person")  # fmt: skip
        rows = _set_gap(store, ctx.now, gap.uid, ["in_review"], to, sub.reason)
        if rows:
            log(store, ctx.now, "keeper", action, gap=gap.uid, why=sub.reason,
                 evidence=sub.cites)  # fmt: skip
        return rows
    if gap.status != "in_review":
        return []

    brain = brain or DEFAULT_BRAIN
    slug = store.slug  # type: ignore[attr-defined]  # the ledger stores know their company
    brain_present(brain, slug)
    subject = sub.subject_uid or ""
    claim = Claim(
        uid=claim_uid(),
        kind=sub.kind,
        subject=subject,
        statement=sub.statement or "",
        value=sub.value,
        about=list(dict.fromkeys([subject, *sub.about])),
        evidence=list(dict.fromkeys(sub.cites)),
        author="keeper",
        why=sub.reason,
        gap=gap.uid,
        created_at=iso(ctx.now),
        updated_at=iso(ctx.now),
    )

    labels = brain.evidence(slug, claim.evidence)
    missing = [u for u in claim.evidence if u not in labels]
    if missing:
        brain_present(brain, slug)  # not every uid gone because the whole graph is
        why = f"evidence_missing: {', '.join(missing)}"
        _write_claim(store, ctx.now, claim, status="rejected", why=why)
        _reopen(store, ctx.now, gap, why, rejected=True)
        log(store, ctx.now, "keeper", "claim_rejected", gap=gap.uid, claim=claim.uid, why=why,
             evidence=claim.evidence)  # fmt: skip
        return [{"uid": claim.uid, "status": "rejected"}]

    clash = conflict(claim.kind, claim.value, brain.source_facts(slug, claim.subject))
    if clash:
        _write_claim(store, ctx.now, claim, status="conflicts_with_source", conflict=clash)
        _set_gap(store, ctx.now, gap.uid, ["in_review"], "resolved", f"conflicts: {clash}")
        log(store, ctx.now, "keeper", "claim_conflicts_with_source", gap=gap.uid,
             claim=claim.uid, why=_both_sides(claim, clash), evidence=claim.evidence)  # fmt: skip
        return [{"uid": claim.uid, "status": "conflicts_with_source"}]

    earlier = [Claim(**c) for c in store.read(
        "ledger/claims", {"statuses": ["accepted"], "limit": EARLIER_LIMIT})]  # fmt: skip
    reasons = critical_reasons(
        claim.kind, claim.subject, claim.about, labels, earlier, brain.high_impact_systems(slug)
    )
    _write_claim(store, ctx.now, claim, critical=bool(reasons), critical_reasons=reasons)
    if reasons:
        log(store, ctx.now, "keeper", "claim_queued", gap=gap.uid, claim=claim.uid,
             why=", ".join(reasons), evidence=claim.evidence)  # fmt: skip
        return [{"uid": claim.uid, "status": "pending_approval"}]

    done = accept(store, ctx, claim, "auto", brain, slug=slug)
    return [{"uid": done.uid, "status": done.status}]


def _ask_archivist(store: WorkStore, ctx: Ctx, gap: Gap, sub: SubmitKeeperDecision) -> list[Row]:
    """Open a topic request for the Archivist (asked_by keeper) and move the gap in_review ->
    waiting_archive; the review's archive step runs it. Once per gap, ever (the guarded
    `ledger/gap_archive_asked`): a second ask is `needs_person`. When the same question is
    already open or running (Ask's, or another gap's), no request opens and the gap stays in
    review: the review releases it to `open`, and its next round can read what was loaded."""
    if gap.status != "in_review":
        return []
    asked = not gap.archive_asked and store.write(
        "ledger/gap_archive_asked", DB_USER, {"uid": gap.uid}
    )
    if not asked:
        rows = _set_gap(store, ctx.now, gap.uid, ["in_review"], "needs_person", ALREADY_ASKED)
        if rows:
            log(store, ctx.now, "keeper", "needs_person", gap=gap.uid, why=ALREADY_ASKED)
        return rows
    topic = (sub.topic or "").strip()
    params = {"uid": archive_uid(), "kind": "topic", "text": topic, "asked_by": "keeper",
              "gap": gap.uid, "norm": norm("topic", topic, []), "now": ctx.now}  # fmt: skip
    [row] = store.write("ledger/archive_open_request", DB_USER, params)
    if not row["created"]:
        log(store, ctx.now, "keeper", "archive_requested", gap=gap.uid,
            why=f"{row['uid']} (already in flight): {topic}")  # fmt: skip
        return [{"uid": gap.uid, "status": "in_review", "request": row["uid"]}]
    rows = _set_gap(store, ctx.now, gap.uid, ["in_review"], "waiting_archive",
                    f"asked the Archivist: {row['uid']}")  # fmt: skip
    log(store, ctx.now, "keeper", "archive_requested", gap=gap.uid, why=f"{row['uid']}: {topic}")
    return [{**r, "request": row["uid"]} for r in rows]


# --- accept, approve, reject -----------------------------------------------------------------


def accept(
    store: WorkStore,
    ctx: Ctx,
    claim: Claim,
    by: str,
    brain: BrainFacts | None = None,
    *,
    slug: str | None = None,
    why: str | None = None,
    action: str = "claim_written",
) -> Claim:
    """Accept a pending claim: project it, then supersede the accepted one it replaces and
    resolve its gap. Logs `action` (actor `by`), or `claim_stale` when projection finds it
    missing; a stale claim supersedes nothing, so the earlier claim stays, and its gap reopens
    with one more attempt (`_reopen(rejected=True)`).

    The guarded move to `accepted` comes first, so a caller that loses a race raises
    `ClaimNotPending` before writing anything. If the projection fails (brain_<slug> vanished:
    `BrainUnavailable`, or any other error), the accept is undone (`_undo_accept`) and the error
    raised: an auto-accept goes `stale` and its gap reopens; a lead's approval goes back to
    `pending_approval`, logged `claim_approval_failed`."""
    brain = brain or DEFAULT_BRAIN
    now = ctx.now
    slug = slug or store.slug  # type: ignore[attr-defined]
    moved = _set_claim(store, now, claim.uid, "accepted", by=by, why=why)
    if not moved:
        raise ClaimNotPending(claim.uid)

    stored = _claim(store, claim.uid)
    try:
        missing = brain.project(slug, [stored.model_dump()])
        if missing and not brain.graph_exists(slug):
            raise BrainUnavailable(slug)  # not missing: the whole graph is gone
    except Exception as e:
        _undo_accept(store, now, stored, by, brain, slug, e)
        raise
    if missing:
        why_stale = "projection: its subject or every evidence uid is gone from the brain"
        _set_claim(store, now, claim.uid, "stale", frm=["accepted"], why=why_stale)
        if stored.gap:
            gap = _gap(store, stored.gap)
            if gap is not None:  # an attempt, as a rejection: else each review pays for the
                _reopen(store, now, gap, why_stale, rejected=True,  # same three jobs again
                        frm=["in_review", "resolved"])  # fmt: skip
        log(store, now, by, "claim_stale", gap=stored.gap, claim=claim.uid, why=why_stale,
             evidence=stored.evidence)  # fmt: skip
        return _claim(store, claim.uid)

    replaced = store.read(
        "ledger/claims_for_subject",
        {"kind": claim.kind, "subject": claim.subject, "statuses": ["accepted"]},
    )
    for old in replaced:
        if old["uid"] == claim.uid:
            continue
        if _set_claim(store, now, old["uid"], "superseded", frm=["accepted"],
                      why=f"superseded by {claim.uid}", valid_to=now):  # fmt: skip
            log(store, now, by, "claim_superseded", gap=old["gap"], claim=old["uid"],
                 why=f"superseded by {claim.uid}", evidence=[claim.uid])  # fmt: skip
            # Logged first: the ledger is the truth. A failed retire leaves the old node current
            # in the brain until the next rebuild; re-projection (keeper/project.py) projects only
            # accepted claims, so it does not repair this, but it does not bring it back either.
            brain.retire(slug, old["uid"], "superseded", iso(now))

    if stored.gap:
        _set_gap(store, now, stored.gap, ["in_review"], "resolved", f"claim {claim.uid}")
    log(store, now, by, action, gap=stored.gap, claim=claim.uid, why=why or stored.why,
         evidence=stored.evidence)  # fmt: skip
    return _claim(store, claim.uid)


def _undo_accept(
    store: WorkStore,
    now: str | float,
    claim: Claim,
    by: str,
    brain: BrainFacts,
    slug: str,
    error: Exception,
) -> None:
    """The projection of a just-accepted claim failed: take the accept back, with one log line.

    - auto (the decide job): `stale`, its gap back to `open` (no attempt used). Not back to
      pending_approval: no lead was asked, and the decide queue would skip the gap for good.
    - a lead's approval: back to `pending_approval` (approved_by and valid_from cleared), logged
      `claim_approval_failed`, so the lead can approve again.

    A failure other than a missing brain may have written the node anyway, so it is retired, best
    effort (the original error is the one raised)."""
    if isinstance(error, BrainUnavailable):
        why = "brain unavailable during projection"
    else:
        why = f"projection failed: {type(error).__name__}: {error}"[:300]
    auto = by == "auto"
    to = "stale" if auto else "pending_approval"
    if not _set_claim(store, now, claim.uid, to, frm=["accepted"], why=why):
        return
    if not isinstance(error, BrainUnavailable):
        try:
            brain.retire(slug, claim.uid, to, iso(now))
        except Exception:  # the projection's error is the one that matters
            pass
    if auto and claim.gap:
        _set_gap(store, now, claim.gap, ["in_review"], "open", why)
    action = "claim_stale" if auto else "claim_approval_failed"
    log(store, now, by, action, gap=claim.gap, claim=claim.uid, why=why,
         evidence=claim.evidence)  # fmt: skip


def approve(
    store: WorkStore,
    slug: str,
    claim_uid: str,
    by: str,
    why: str | None,
    brain: BrainFacts | None = None,
    *,
    now: str | float | None = None,
) -> Claim:
    """A lead approves a pending claim. The sources are checked again first: if they now
    contradict it, it becomes `conflicts_with_source` instead (never projected)."""
    brain = brain or DEFAULT_BRAIN
    now = int(time.time()) if now is None else now
    claim = _pending(store, claim_uid)
    brain_present(brain, slug)
    clash = conflict(claim.kind, claim.value, brain.source_facts(slug, claim.subject))
    if clash:
        if not _set_claim(store, now, claim.uid, "conflicts_with_source", by=by, why=why,
                          conflict=clash):  # fmt: skip
            raise ClaimNotPending(claim.uid)
        if claim.gap:
            _set_gap(store, now, claim.gap, ["in_review"], "resolved", f"conflicts: {clash}")
        log(store, now, by, "claim_conflicts_with_source", gap=claim.gap, claim=claim.uid,
             why=_both_sides(claim, clash), evidence=claim.evidence)  # fmt: skip
        return _claim(store, claim.uid)
    return accept(store, _ctx(now), claim, by, brain, slug=slug, why=why, action="claim_approved")


def reject(
    store: WorkStore,
    slug: str,
    claim_uid: str,
    by: str,
    why: str | None,
    *,
    now: str | float | None = None,
) -> Claim:
    """A lead rejects a pending claim: its gap goes back to `open` with one more attempt
    (`needs_person` at MAX_ATTEMPTS)."""
    now = int(time.time()) if now is None else now
    claim = _pending(store, claim_uid)
    if not _set_claim(store, now, claim.uid, "rejected", by=by, why=why):
        raise ClaimNotPending(claim.uid)
    if claim.gap:
        gap = _gap(store, claim.gap)
        if gap is not None:
            _reopen(store, now, gap, f"rejected by {by}", rejected=True)
    log(store, now, by, "claim_rejected", gap=claim.gap, claim=claim.uid, why=why,
         evidence=claim.evidence)  # fmt: skip
    return _claim(store, claim.uid)


# --- ledger helpers --------------------------------------------------------------------------


def _ctx(now: str | float) -> Ctx:
    """A Ctx for a lead's approval (not an agent job). Imported here: agents.roles imports
    roles/keeper.py, which imports this module."""
    from agents.roles.base import Ctx

    return Ctx("keeper", DB_USER, now)  # type: ignore[arg-type]  # iso() takes either


def brain_present(brain: BrainFacts, slug: str) -> None:
    """Raise `BrainUnavailable` when brain_<slug> does not exist (the review run checks this
    before every job's writes, too)."""
    if not brain.graph_exists(slug):
        raise BrainUnavailable(slug)


def log(store: WorkStore, now: str | float, actor: str, action: str, **fields: Any) -> None:
    entry = {"uid": log_uid(now), "at": now, "actor": actor, "action": action, **fields}
    store.write("ledger/log", DB_USER, entry)


def _gap(store: WorkStore, uid: str) -> Gap | None:
    rows = store.read("ledger/get_gap", {"uid": uid})
    return Gap(**rows[0]) if rows else None


def _claim(store: WorkStore, uid: str) -> Claim:
    [row] = store.read("ledger/get_claim", {"uid": uid})
    return Claim(**row)


def _pending(store: WorkStore, uid: str) -> Claim:
    rows = store.read("ledger/get_claim", {"uid": uid})
    if not rows or rows[0]["status"] != "pending_approval":
        raise ClaimNotPending(uid)
    return Claim(**rows[0])


def _write_claim(store: WorkStore, now: str | float, claim: Claim, **fields: Any) -> None:
    store.write("ledger/write_claim", DB_USER, {**claim.model_dump(), **fields, "now": now})


def _set_claim(
    store: WorkStore,
    now: str | float,
    uid: str,
    to: str,
    *,
    frm: list[str] | None = None,
    **fields: Any,
) -> list[Row]:
    params = {"uid": uid, "from": frm or ["pending_approval"], "to": to, "now": now, **fields}
    return store.write("ledger/set_claim_status", DB_USER, params)


def _set_gap(
    store: WorkStore,
    now: str | float,
    uid: str,
    frm: list[str],
    to: str,
    reason: str | None,
    attempts_inc: int = 0,
) -> list[Row]:
    params = {"uid": uid, "from": frm, "to": to, "reason": reason, "now": now}
    return store.write("ledger/set_gap_status", DB_USER, {**params, "attempts_inc": attempts_inc})


def _reopen(
    store: WorkStore,
    now: str | float,
    gap: Gap,
    reason: str,
    *,
    rejected: bool,
    frm: list[str] | None = None,
) -> list[Row]:
    """Send a gap back to `open`; a rejection adds an attempt, and at MAX_ATTEMPTS the gap
    needs a person instead."""
    inc = 1 if rejected else 0
    to = "needs_person" if gap.attempts + inc >= MAX_ATTEMPTS else "open"
    return _set_gap(store, now, gap.uid, frm or ["in_review"], to, reason, inc)


def _both_sides(claim: Claim, clash: str) -> str:
    said = claim.value or claim.statement
    return f"claim: {claim.kind} of {claim.subject} is {said}; sources: {clash}"
