"""Trace routes: how the brain does on live questions, and the thumbs on one answer.

Why: real company graphs have no gold answers, so live use is watched with numbers that need
none (`agents/traces.py`). GET .../traces/summary?days=7 gives the window's rates (no answer,
step limit, refusal, nudges, rejected submits, zero-source answers, ...), p50/p95 latency and
tokens, and the thumbs counts. POST .../traces/{trace_id}/feedback stores a thumbs up or down
(or takes it back) on one turn the Ask page answered; thumbs-down turns become draft eval cases
(`python -m evals.drafts`). A trace id only counts for its own company (404 otherwise).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from brain.agents.traces import TraceSummary, summarize, window
from brain.api.ask import Asker, get_asker
from brain.api.deps import company_slug
from brain.api.models import FeedbackIn, FeedbackOut

router = APIRouter(prefix="/companies/{slug}/traces", tags=["traces"])
Slug = Annotated[str, Depends(company_slug)]
TraceId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


@router.get("/summary")
def get_summary(
    slug: Slug,
    asker: Annotated[Asker, Depends(get_asker)],
    days: Annotated[int, Query(ge=1, le=365)] = 7,
) -> TraceSummary:
    since, until = window(days)
    return summarize(asker.traces(slug).read(since=since), since, until)


@router.post("/{trace_id}/feedback")
def post_feedback(
    slug: Slug,
    trace_id: TraceId,
    body: FeedbackIn,
    asker: Annotated[Asker, Depends(get_asker)],
) -> FeedbackOut:
    try:
        trace = asker.traces(slug).rate(trace_id, body.rating, body.note)
    except OSError as exc:
        raise HTTPException(status_code=503, detail="The rating could not be saved.") from exc
    if trace is None or trace.feedback is None:
        raise HTTPException(status_code=404, detail=f"No answer {trace_id} for {slug}")
    return FeedbackOut(trace_id=trace.id, rating=trace.feedback.rating, note=trace.feedback.note)
