"""The work behind one claim: what pm, qa and the Keeper did on the way to it, for the review page.

Why: a lead deciding a claim should see that agents worked it out and how: the gap they were
answering, what pm and qa each drafted from which uids, every graph tool each job ran, and the
Keeper's decision. All of it is already in the ledger; this joins it for one claim:

- the review: of the reviews that picked the claim's gap (`ledger/reviews_for_gap`, newest
  first), the one whose keeper decide submit names the claim; else the newest that started
  before the claim was written.
- jobs: that review's steps (`ledger/review_steps`) cut into jobs. Jobs run one after another,
  so a job is an actor's graph steps up to and including its submit step; a job belongs to the
  gap when its submit's subject is the gap (keeper decide) or one of its consults
  (`consult:<gap>:<role>:<attempt>`, pm and qa). pm's later follow-up is not part of it.
- consults: the pm and qa answers of the gap's current attempt (`ledger/consults_for_gap`), the
  one that produced a claim still waiting for a lead.
- log: every entry about the gap, oldest first (opened, picked, consulted, the claim written).

A claim filed from an Ask interview has no review: its trail is the log alone.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from agents.activity import ActivityStep
from agents.keeper.model import Claim, Consult, LogEntry, Review, ReviewStep
from agents.work.store import WorkStore

LOG_LIMIT = 100


class TrailJob(BaseModel):
    """One job of a review: an actor's graph steps, then its submit."""

    actor: str  # "pm", "qa" or "keeper"
    tool: str  # the submit tool, e.g. submit_consult, submit_keeper_decision
    steps: list[ActivityStep] = []  # the graph-tool calls, in order
    submit: dict[str, Any] = {}  # the submit step's input (subject, outcome, kind, claim, ...)
    wrote: bool = True  # False when the submit wrote nothing
    error: str | None = None
    consult: Consult | None = None  # a pm or qa job's answer


class ClaimTrail(BaseModel):
    claim: str
    review: Review | None = None
    jobs: list[TrailJob] = []
    log: list[LogEntry] = []  # oldest first


def gap_of(subject: str) -> str | None:
    """The gap a submit's subject is about: the gap itself, or the gap of a consult uid."""
    if subject.startswith("gap:"):
        return subject
    if subject.startswith("consult:"):
        return subject.removeprefix("consult:").rsplit(":", 2)[0]
    return None


def jobs_of(steps: list[ReviewStep]) -> list[tuple[ReviewStep, list[ReviewStep]]]:
    """A review's steps as (submit, graph steps before it) per job, in the order they ran."""
    pending: dict[str, list[ReviewStep]] = {}
    jobs = []
    for step in sorted(steps, key=lambda s: s.n):
        if step.kind == "submit":
            jobs.append((step, pending.pop(step.actor, [])))
        else:
            pending.setdefault(step.actor, []).append(step)
    return jobs


def _activity(s: ReviewStep) -> ActivityStep:
    return ActivityStep(
        n=s.n,
        actor=s.actor,
        tool=s.tool,
        kind=s.kind,
        input=s.input,
        status="failed" if s.status == "running" else s.status,
        count=s.count,
        error="interrupted" if s.status == "running" else s.error,
        touched=list(dict.fromkeys(s.touched)),
    )


def _review_of(claim: Claim, reviews: list[Review], steps: list[ReviewStep]) -> Review | None:
    wrote = {s.review for s in steps if s.kind == "submit" and s.input.get("claim") == claim.uid}
    for review in reviews:
        if review.uid in wrote:
            return review
    return next((r for r in reviews if r.started_at <= claim.created_at), None)


def claim_trail(store: WorkStore, claim: Claim) -> ClaimTrail:
    if not claim.gap:
        return ClaimTrail(claim=claim.uid)
    gap = claim.gap
    entries = store.read("ledger/read_log", {"limit": LOG_LIMIT, "gap": gap})
    log = [LogEntry(**e) for e in reversed(entries)]
    reviews = [Review(**r) for r in store.read("ledger/reviews_for_gap", {"gap": gap})]
    steps = [
        ReviewStep(**s)
        for s in store.read("ledger/review_steps", {"reviews": [r.uid for r in reviews]})
    ] if reviews else []  # fmt: skip
    review = _review_of(claim, reviews, steps)
    if review is None:
        return ClaimTrail(claim=claim.uid, log=log)

    rows = store.read("ledger/consults_for_gap", {"gap": gap})
    consults = {c.uid: c for c in (Consult(**r) for r in rows)}
    jobs = []
    for submit, graph in jobs_of([s for s in steps if s.review == review.uid]):
        subject = str(submit.input.get("subject", ""))
        if gap_of(subject) != gap:
            continue
        jobs.append(
            TrailJob(
                actor=submit.actor,
                tool=submit.tool,
                steps=[_activity(s) for s in graph],
                submit=submit.input,
                wrote=submit.status == "done",
                error=submit.error,
                consult=consults.get(subject),
            )
        )
    return ClaimTrail(claim=claim.uid, review=review, jobs=jobs, log=log)
