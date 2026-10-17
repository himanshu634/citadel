"""Gaps from live Ask traffic: a failed question or a thumbs-down becomes a gap on the ledger.

Why: the Keeper reviews what the brain could not answer. The Ask turns that failed (no answer, or
an answer that cites nothing) and the answers a person marked wrong are the best list of that.
Both open a gap, or bump the open one for the same question (the ledger dedupes by the
normalised text, per kind), and cite the turn's trace:

    note_trace(store, trace, now)          # failed_question, when text is None or sources == 0
                                           # (not an answered interview turn: it read open_gaps)
    note_feedback(store, trace, "down", now)  # thumbs_down

Best effort: a gap is a side record of an answer, so every failure is caught, written to stderr
and returned as None. A gap write never fails or changes an answer or a rating.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

from agents.keeper.model import gap_uid
from agents.keeper.rules import normalise
from agents.traces import Rating, Trace
from agents.work.store import WorkStore

WRITER = "citadel_brain"  # the database user the Ask path writes as
INTERVIEW_TOOL = "open_gaps"  # a turn that ran it asked the person, it did not answer


def utc_now() -> str:
    """The ledger's timestamp for now: ISO-8601 UTC text."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def note_trace(store: WorkStore, trace: Trace, now: str) -> str | None:
    """Open or bump a `failed_question` gap when the turn had no answer or cited no source.
    Returns the gap uid, or None when the turn was fine (or the write failed). An answered turn
    that read `open_gaps` was Ask interviewing the person (`keeper/interview.py`): with no gap
    to ask about it cites nothing, and is not a question the brain failed."""
    if trace.text is not None and (trace.sources > 0 or INTERVIEW_TOOL in trace.tools):
        return None
    return _open(store, "failed_question", trace, now)


def note_feedback(store: WorkStore, trace: Trace, rating: Rating | None, now: str) -> str | None:
    """Open or bump a `thumbs_down` gap when the answer got a thumbs down."""
    if rating != "down":
        return None
    return _open(store, "thumbs_down", trace, now)


def _open(store: WorkStore, kind: str, trace: Trace, now: str) -> str | None:
    try:
        norm = normalise(trace.question)
        if not norm:  # "?" or "...": every such question would share one key
            return None
        [row] = store.write(
            "ledger/open_gap",
            WRITER,
            {
                "uid": gap_uid(),
                "kind": kind,
                "text": trace.question,
                "norm": norm,
                "subject": None,
                "about": list(trace.cited),
                "trace_id": trace.id,
                "now": now,
            },
        )
        return row["uid"]
    except Exception as e:  # best effort: never fail an answer over a gap
        print(f"keeper: could not note a {kind} gap for trace {trace.id}: {e!r}", file=sys.stderr)
        return None
