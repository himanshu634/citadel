"""The Keeper's records: what the ledger graph keeper_<slug> holds.

Why: the Keeper's work must survive a rebuild of brain_<slug>, so it lives in its own graph:
gaps, the consults pm and qa answer, the claims the Keeper writes, pm's follow-ups, the log and
the review runs. These models are the rows the ledger's named queries return (`store.py`), the
same from FalkorDB and from the in-memory store.

Timestamps are ISO-8601 UTC strings (`iso`), so they sort as text in Cypher and in Python.
Records point at brain nodes by uid string; graphs cannot link to each other.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

GapKind = Literal[
    "failed_question", "thumbs_down", "stale_owner", "unowned_hot_system", "archive_conflict"
]
GapStatus = Literal["open", "in_review", "waiting_archive", "resolved", "needs_person", "dismissed"]
ClaimKind = Literal["owner", "expert", "decision", "fact", "link"]
ClaimStatus = Literal[
    "pending_approval", "accepted", "rejected", "superseded", "stale", "conflicts_with_source"
]

# Gaps the Keeper notices itself are about one subject, not a question's text, so they dedupe on
# (kind, subject). Mirrored in apps/brain/queries/ledger/open_gap.cypher.
NOTICING_KINDS: tuple[str, ...] = ("stale_owner", "unowned_hot_system")
# A gap in one of these statuses absorbs a repeat (count + 1) instead of a new gap opening.
# `waiting_archive` is a gap whose answer the Archivist is looking for in older items.
LIVE_GAP: tuple[str, ...] = ("open", "in_review", "waiting_archive")


class Gap(BaseModel):
    uid: str
    kind: GapKind
    text: str
    norm: str | None = None  # the normalised question text, the dedupe key for questions
    status: GapStatus = "open"
    count: int = 1  # how often it was seen while open or in review
    attempts: int = 0  # rejected claims so far; at 2 the gap needs a person
    created_at: str
    updated_at: str
    trace_ids: list[str] = Field(default_factory=list)  # Ask traces that raised it
    about: list[str] = Field(default_factory=list)  # brain uids it is about
    subject: str | None = None  # the brain uid a noticing gap is about, its dedupe key
    reason: str | None = None  # why it last changed status (needs_person, dismissed, ...)
    archive_asked: bool = False  # the Keeper already asked the Archivist about it (once per gap)


class LogEntry(BaseModel):
    """One line of the append-only log: who did what, why, and on which evidence."""

    uid: str
    at: str
    actor: str  # "keeper", "pm", "qa", an agent uid, the approver's name, or "auto"
    action: str  # gap_opened, consulted, claim_written, ..., episode, review_done
    why: str | None = None
    gap: str | None = None
    claim: str | None = None
    evidence: list[str] = Field(default_factory=list)


class Review(BaseModel):
    """One bounded review run. At most one per company is `running`."""

    uid: str
    slug: str
    trigger: Literal["build", "manual", "approval"]
    state: Literal["running", "done", "stopped", "failed", "skipped"] = "running"
    budget: int
    started_at: str
    ended_at: str | None = None
    stop: str | None = None  # why it ended early, e.g. "restart", "brain_unavailable"
    gaps: list[str] = Field(default_factory=list)  # the gaps it picked, in pick order
    gap_text: str | None = None  # the first picked gap's text (a gap's text never changes)


StepStatus = Literal["running", "done", "failed"]


class ReviewStep(BaseModel):
    """One step of a review, for the Systems page's activity trail (`agents/activity.py`): a
    graph-tool call of a pm, qa or keeper job (kind "graph"), or a job's submit (kind
    "submit"). Numbered 1.. in the order they ran within the review."""

    review: str  # the Review's uid
    n: int
    actor: str  # "pm", "qa" or "keeper"
    tool: str
    kind: Literal["graph", "submit"] = "graph"
    input: dict[str, Any] = Field(default_factory=dict)  # stored as JSON text
    status: StepStatus = "running"
    count: int | None = None  # rows the tool returned
    error: str | None = None
    touched: list[str] = Field(default_factory=list)  # brain_<slug> uids, deduped in order
    started_at: str
    ended_at: str | None = None

    @field_validator("input", mode="before")
    @classmethod
    def _parse_input(cls, v: Any) -> Any:
        return json.loads(v) if isinstance(v, str) else v


class Consult(BaseModel):
    """One role's answer to one gap: a draft claim citing uids it saw, or can_ground False."""

    uid: str  # consult:<gap>:<role>:<attempt>, one per role per attempt at the gap
    gap: str
    role: Literal["pm", "qa"]
    attempt: int = 0  # the gap's `attempts` when it was posted; a reopened gap asks again
    status: Literal["open", "answered"] = "open"
    can_ground: bool | None = None  # None until answered
    kind: ClaimKind | None = None
    subject: str | None = None
    statement: str | None = None
    value: str | None = None
    cites: list[str] = Field(default_factory=list)
    created_at: str  # when it was posted; the role's queue reads oldest first
    answered_at: str | None = None


class Claim(BaseModel):
    """What the Keeper holds true beyond the sources. Never deleted: it is superseded (valid_to),
    rejected, marked stale or conflicts_with_source instead."""

    uid: str
    kind: ClaimKind
    subject: str  # the brain uid it is about, e.g. system:billing
    statement: str
    value: str | None = None  # e.g. the owner's uid for an owner claim
    about: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)  # brain uids that support it
    status: ClaimStatus = "pending_approval"
    critical: bool = False
    critical_reasons: list[str] = Field(default_factory=list)
    conflict: str | None = None  # the source fact it contradicts (conflicts_with_source)
    valid_from: str | None = None  # set when it is accepted
    valid_to: str | None = None  # set when it is superseded
    author: str  # "keeper", or the role that drafted it
    approved_by: str | None = None  # the name the lead typed (not verified: no sign-in), or "auto"
    why: str | None = None  # why it has its current status
    gap: str | None = None
    created_at: str
    updated_at: str
    follow_up_tries: int = 0  # pm follow-up jobs that ended with no task (one try, then skipped)


class FollowUp(BaseModel):
    """The task pm opens for an accepted owner/expert/decision claim, or to fix a source."""

    uid: str  # followup:<claim>, one per claim
    claim: str
    title: str
    body: str = ""
    by: str = "pm"
    status: Literal["open", "done"] = "open"
    created_at: str


RequestStatus = Literal["open", "running", "answered", "failed", "refused"]
# A request in one of these statuses absorbs the same question (rule 16). Mirrored in
# apps/brain/queries/ledger/archive_open_request.cypher.
LIVE_REQUEST: tuple[str, ...] = ("open", "running")
RequestOutcome = Literal["found", "nothing_found", "already_in_brain"]
Verdict = Literal["holds", "superseded", "conflicts"]


class ArchiveRequest(BaseModel):
    """One ask of the Archivist: look for older items by reference or by topic. The Archivist
    reads its queue, runs, and records the outcome here (`ledger/archive_*`)."""

    uid: str  # archive:<12 hex>
    kind: Literal["reference", "topic"]
    text: str
    refs: list[str] = Field(default_factory=list)  # the exact refs of a reference request
    from_uid: str | None = None  # the brain uid the person was looking at, if any
    asked_by: Literal["ask", "keeper"]
    gap: str | None = None  # the Keeper gap it serves
    thread: str | None = None  # the Ask thread that raised it
    status: RequestStatus = "open"
    outcome: RequestOutcome | None = None  # set when answered
    summary: str | None = None
    reason: str | None = None  # why it failed or was refused
    norm: str  # the dedupe key (`archivist.rules.norm`)
    partial: bool = False  # a budget ran out: not served from memory later
    calls: int = 0  # external calls it used
    created_at: str
    updated_at: str


class ArchiveFind(BaseModel):
    """One older item the Archivist stands behind for a request, with the proof it checked."""

    request: str  # the ArchiveRequest's uid
    uid: str  # the brain uid the item loads as
    url: str | None = None
    title: str
    date: str | None = None  # the item's own date, ISO
    why: str  # why it answers the request
    quote: str  # a passage of its fetched text
    verdict: Verdict
    evidence: list[str] = Field(default_factory=list)  # brain uids that back the verdict
    superseded_by: str | None = None  # the newer uid, for verdict "superseded"


def iso(now: str | float) -> str:
    """A ledger timestamp: ISO strings pass through; epoch seconds (`Ctx.now`) become UTC ISO."""
    if isinstance(now, str):
        return now
    return datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hex(n: int) -> str:
    return uuid.uuid4().hex[:n]


def gap_uid() -> str:
    return f"gap:{_hex(12)}"


def review_uid() -> str:
    return f"review:{_hex(8)}"


def log_uid(at: str | float) -> str:
    """log:<compact timestamp>-<6 hex>, e.g. log:20261017T100000Z-3fa2c1."""
    return f"log:{re.sub(r'[^0-9A-Za-z]', '', iso(at))}-{_hex(6)}"


def claim_uid() -> str:
    return f"claim:{_hex(12)}"


def consult_uid(gap: str, role: str, attempt: int) -> str:
    """Mirrored in apps/brain/queries/ledger/post_consult.cypher."""
    return f"consult:{gap}:{role}:{attempt}"


def archive_uid() -> str:
    return f"archive:{_hex(12)}"


def followup_uid(claim: str) -> str:
    """Mirrored in apps/brain/queries/ledger/open_followup.cypher."""
    return f"followup:{claim}"
