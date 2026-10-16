"""The Keeper's records: what the ledger graph keeper_<slug> holds.

Why: the Keeper's work (gaps it reviews, the log of what it did, its review runs) must survive a
rebuild of brain_<slug>, so it lives in its own graph. These models are the rows the ledger's
named queries return (`store.py`), the same from FalkorDB and from the in-memory store.

Timestamps are ISO-8601 UTC strings (`iso`), so they sort as text in Cypher and in Python.
Records point at brain nodes by uid string; graphs cannot link to each other.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

GapKind = Literal["failed_question", "thumbs_down", "stale_owner", "unowned_hot_system"]
GapStatus = Literal["open", "in_review", "resolved", "needs_person", "dismissed"]

# Gaps the Keeper notices itself are about one subject, not a question's text, so they dedupe on
# (kind, subject). Mirrored in apps/brain/queries/ledger/open_gap.cypher.
NOTICING_KINDS: tuple[str, ...] = ("stale_owner", "unowned_hot_system")
# A gap in one of these statuses absorbs a repeat (count + 1) instead of a new gap opening.
LIVE_GAP: tuple[str, ...] = ("open", "in_review")


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
    stop: str | None = None  # why it ended early, e.g. "restart" or "brain_unavailable"


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
