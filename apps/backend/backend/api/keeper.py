"""Keeper routes: the ledger's gaps, claims, log and follow-ups, a lead's approve/reject, and
review runs started, followed (Server-Sent Events) and stopped.

Why: the Keeper page reads the ledger (keeper_<slug>) only through these routes. Reviews run in
`KeeperRuns` (app.state.keeper, so tests hand in an offline one). An approval starts a budget-0
review, so pm's follow-up for the accepted claim shows without waiting for the next build.
While the company builds, Review now, approve and reject are 409 with `BUILDING` as the detail:
a rebuild's brain_<slug> is empty until ingest ends.

/review/events sends the latest review as a `snapshot` first, then one `review` message per
ReviewEvent of the run in this process (the ones so far, then the live ones); it ends with the
run (an event of kind done, stopped, failed or skipped), like the build stream.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Literal, get_args

import anyio
from agents.keeper import decide
from agents.keeper.model import Claim, ClaimStatus, FollowUp, Gap, GapStatus, LogEntry, Review
from brain.config import get_settings
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sse_starlette import EventSourceResponse

from backend.api.deps import Slug, sse
from backend.api.models import ApprovalIn, KeeperEvent
from backend.keeper_runs import BUILDING, ENDS, BrainBuilding, KeeperRuns, ReviewNotStarted

log = logging.getLogger(__name__)
router = APIRouter(tags=["keeper"])

PREFIX = "/companies/{slug}/keeper"
Limit = Annotated[int, Query(ge=1, le=500)]


def get_keeper(request: Request) -> KeeperRuns:
    return request.app.state.keeper


Keeper = Annotated[KeeperRuns, Depends(get_keeper)]


# --- the ledger -------------------------------------------------------------------------------


@router.get(f"{PREFIX}/gaps")
def gaps(
    slug: Slug, runs: Keeper, status: GapStatus | None = None, limit: Limit = 100
) -> list[Gap]:
    """Newest first; every status unless `status` is given."""
    statuses = [status] if status else list(get_args(GapStatus))
    rows = runs.store_for(slug).read("ledger/gaps", {"statuses": statuses, "limit": limit})
    return [Gap(**r) for r in rows]


@router.get(f"{PREFIX}/claims")
def claims(
    slug: Slug, runs: Keeper, status: ClaimStatus | None = None, limit: Limit = 100
) -> list[Claim]:
    """Newest first; every status unless `status` is given."""
    statuses = [status] if status else list(get_args(ClaimStatus))
    rows = runs.store_for(slug).read("ledger/claims", {"statuses": statuses, "limit": limit})
    return [Claim(**r) for r in rows]


@router.get(f"{PREFIX}/log")
def read_log(
    slug: Slug,
    runs: Keeper,
    limit: Limit = 50,
    gap: str | None = None,
    claim: str | None = None,
) -> list[LogEntry]:
    """Newest first; only one gap's or one claim's entries when asked."""
    params = {"limit": limit, "gap": gap, "claim": claim}
    return [LogEntry(**r) for r in runs.store_for(slug).read("ledger/read_log", params)]


@router.get(f"{PREFIX}/followups")
def followups(
    slug: Slug, runs: Keeper, status: Literal["open", "done"] | None = None, limit: Limit = 100
) -> list[FollowUp]:
    rows = runs.store_for(slug).read("ledger/followups", {"status": status, "limit": limit})
    return [FollowUp(**r) for r in rows]


# --- a lead's decision ------------------------------------------------------------------------


def _not_building(runs: KeeperRuns, slug: str) -> None:
    if runs.building(slug):
        raise HTTPException(status_code=409, detail=BUILDING)


def _known_claim(runs: KeeperRuns, slug: str, uid: str) -> None:
    if not runs.store_for(slug).read("ledger/get_claim", {"uid": uid}):
        raise HTTPException(status_code=404, detail=f"No claim {uid}")


def _not_pending(uid: str) -> HTTPException:
    return HTTPException(
        status_code=409, detail=f"Claim {uid} is not waiting for approval: it was decided already."
    )


@router.post(f"{PREFIX}/claims/{{uid}}/approve")
def approve(slug: Slug, uid: str, body: ApprovalIn, runs: Keeper) -> Claim:
    """Accept a pending claim (or `conflicts_with_source` when the sources now say otherwise),
    then start a budget-0 review so pm's follow-up appears. 409 while the company builds."""
    _not_building(runs, slug)
    _known_claim(runs, slug, uid)
    store = runs.store_for(slug)
    try:
        claim = decide.approve(store, slug, uid, body.by, body.why or None, brain=runs.brain)
    except decide.ClaimNotPending as exc:
        raise _not_pending(uid) from exc
    except decide.BrainUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=f"The brain of {slug} is not there (brain_{slug} is missing). "
            "Build the company, then approve again.",
        ) from exc
    try:
        runs.start_soon(slug, "approval", 0)  # the response does not wait for it
    except BrainBuilding:  # a build began since: its own review writes the follow-up
        pass
    except Exception:  # the approval stands; the next review writes the follow-up
        log.exception("could not start the review after approving %s", uid)
    return claim


@router.post(f"{PREFIX}/claims/{{uid}}/reject")
def reject(slug: Slug, uid: str, body: ApprovalIn, runs: Keeper) -> Claim:
    """Reject a pending claim: its gap goes back to open with one more attempt. 409 while the
    company builds (the gap would be picked again by a review of the empty brain)."""
    _not_building(runs, slug)
    _known_claim(runs, slug, uid)
    try:
        return decide.reject(runs.store_for(slug), slug, uid, body.by, body.why or None)
    except decide.ClaimNotPending as exc:
        raise _not_pending(uid) from exc


# --- review runs ------------------------------------------------------------------------------


@router.post(f"{PREFIX}/review", status_code=202)
def start_review(slug: Slug, runs: Keeper) -> Review:
    """Review now (budget `keeper_budget`); the running review when there is one; 409 while the
    company builds."""
    try:
        return runs.start(slug, "manual", get_settings().keeper_budget)
    except BrainBuilding as exc:
        raise HTTPException(status_code=409, detail=BUILDING) from exc
    except ReviewNotStarted as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post(f"{PREFIX}/review/stop", status_code=202)
def stop_review(slug: Slug, runs: Keeper) -> Review:
    """Ask the running review to stop at its next job; the review says when it has."""
    if not runs.stop(slug) or (current := runs.current(slug)) is None:
        raise HTTPException(status_code=404, detail=f"No review of {slug} is running")
    return current


async def review_events(runs: KeeperRuns, slug: str) -> AsyncIterator[dict]:
    """The latest review, then each event of this process's run until it ends."""
    events = runs.subscribe(slug)  # before the snapshot, so no event falls between
    try:
        current = await anyio.to_thread.run_sync(runs.current, slug)
        if current is not None:
            yield {"event": "snapshot", "data": current.model_dump_json()}
        async for event in events:
            payload = KeeperEvent(**dataclasses.asdict(event))
            yield {"event": "review", "data": payload.model_dump_json()}
            if event.kind in ENDS:
                return
    finally:
        await events.aclose()


@router.get(f"{PREFIX}/review/events")
def events(slug: Slug, runs: Keeper) -> EventSourceResponse:
    if runs.current(slug) is None and not runs.running(slug):  # 404 before the stream starts
        raise HTTPException(status_code=404, detail=f"No review of {slug} yet")
    return sse(review_events(runs, slug))
