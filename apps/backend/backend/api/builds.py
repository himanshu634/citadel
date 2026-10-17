"""Build routes: start, inspect and stop a company's build, and follow it over Server-Sent Events.

Why: a build runs for minutes in the job runner, so these routes only start, read and stop jobs.
Progress reaches the browser over two SSE streams:
- /api/companies/{slug}/builds/current/events: the build's snapshot first (so a page opened
  mid-build can draw its stage table), then each build event; it ends with the build.
- /api/events: one `status` message per build event of any company, carrying that company as
  the company list reports it (CompanyOut), for the rail badges. It never ends; a ping keeps it
  open.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import AsyncIterator
from typing import Annotated

import anyio
from brain.events import BuildEvent
from fastapi import APIRouter, Body, HTTPException
from sse_starlette import EventSourceResponse

from backend import registry
from backend.api import companies
from backend.api.deps import Runner, Slug, StartLock, sse
from backend.api.models import BuildIn, CompanyOut
from backend.jobs import ACTIVE, BuildSnapshot, JobRunner, JobRunning, is_active

router = APIRouter(tags=["builds"])


def _current(runner: JobRunner, slug: str) -> BuildSnapshot:
    snap = runner.current(slug)
    if snap is None:
        raise HTTPException(status_code=404, detail=f"No build for {slug} yet")
    return snap


def _known_keys(slug: str, keys: list[str]) -> set[str]:
    known = companies.source_keys(slug)
    if not keys or not set(keys) <= known:
        unknown = sorted(set(keys) - known) or ["(none named)"]
        raise HTTPException(status_code=422, detail=f"{slug} has no source {', '.join(unknown)}")
    return set(keys)


@router.post("/companies/{slug}/builds", status_code=202)
def start_build(
    slug: Slug, runner: Runner, lock: StartLock, body: Annotated[BuildIn | None, Body()] = None
) -> BuildSnapshot:
    """Queued when two builds already run elsewhere; 409 when this company has one. `sources`
    limits the download to those keys (422 for a key the company does not have)."""
    refetch = _known_keys(slug, body.sources) if body and body.sources is not None else None
    with lock:
        try:
            return runner.start(slug, "build", full=body.full if body else False, refetch=refetch)
        except JobRunning as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/companies/{slug}/builds/current")
def current_build(slug: Slug, runner: Runner) -> BuildSnapshot:
    """The running build, else the last one (it survives a restart)."""
    return _current(runner, slug)


@router.delete("/companies/{slug}/builds/current", status_code=202)
def stop_build(slug: Slug, runner: Runner) -> BuildSnapshot:
    """Ask the build to stop at its next event or step; the snapshot says when it has."""
    if not runner.stop(slug):
        raise HTTPException(status_code=404, detail=f"No build of {slug} is running")
    return _current(runner, slug)


def _ends_build(event: BuildEvent) -> bool:
    return event.stage == "done" or event.status in ("failed", "stopped")


async def progress_events(runner: JobRunner, slug: str) -> AsyncIterator[dict]:
    """The snapshot, then each event of the build until it ends."""
    snap = await anyio.to_thread.run_sync(runner.current, slug)
    if not is_active(snap):  # nothing more will happen: no subscription
        if snap is not None:
            yield {"event": "snapshot", "data": snap.model_dump_json()}
        return
    events = runner.subscribe(slug)  # before reading the snapshot, so no event falls between
    try:
        snap = await anyio.to_thread.run_sync(runner.current, slug)
        yield {"event": "snapshot", "data": snap.model_dump_json()}
        if snap.state not in ACTIVE:
            return
        catching_up = True  # the first queued events may already be in the snapshot
        async for event in events:
            catching_up = catching_up and event in snap.events
            if not catching_up:
                yield {"event": "build", "data": json.dumps(dataclasses.asdict(event))}
            if _ends_build(event):
                return
    finally:
        await events.aclose()


@router.get("/companies/{slug}/builds/current/events")
def build_events(slug: Slug, runner: Runner) -> EventSourceResponse:
    _current(runner, slug)  # 404 before the stream starts
    return sse(progress_events(runner, slug))


def _company(runner: JobRunner, slug: str) -> CompanyOut:
    return companies.company_out(runner, registry.entry(slug))


async def status_events(runner: JobRunner) -> AsyncIterator[dict]:
    """A `status` message for each build event of any company: that company as GET
    /api/companies reports it (CompanyOut), recomputed at that moment."""
    events = runner.subscribe(None)
    try:
        async for event in events:
            company = await anyio.to_thread.run_sync(_company, runner, event.slug)
            yield {"event": "status", "data": company.model_dump_json()}
    finally:
        await events.aclose()


@router.get("/events")
async def all_events(runner: Runner) -> EventSourceResponse:
    return sse(status_events(runner))
