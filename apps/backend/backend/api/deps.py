"""Shared request dependencies.

Why: every company route is /api/companies/{slug}/..., and the slug picks a graph and a YAML
file. It is resolved here, once, and nowhere else reads it from a body, header or cookie. The
job runner and the lock around starting a build live on the app, so tests can hand in their own.
"""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sse_starlette import EventSourceResponse

from backend import registry
from backend.jobs import JobRunner

PING_SECONDS = 15  # every SSE stream pings this often, so proxies keep it open


def company_slug(slug: str) -> str:
    """The path slug if it names a company file, else 404 (`registry.exists` checks the
    pattern too)."""
    if not registry.exists(slug):
        raise HTTPException(status_code=404, detail=f"No company {slug}")
    return slug


def get_runner(request: Request) -> JobRunner:
    return request.app.state.runner


def start_lock(request: Request) -> threading.Lock:
    """Held while a route checks for a running build, writes the YAML and starts a job, so a
    Settings save can never write a file under a build that started a moment earlier."""
    return request.app.state.start_lock


def sse(events: AsyncIterator[dict]) -> EventSourceResponse:
    """An SSE response for `events`, with the shared ping."""
    return EventSourceResponse(events, ping=PING_SECONDS)


Slug = Annotated[str, Depends(company_slug)]
Runner = Annotated[JobRunner, Depends(get_runner)]
StartLock = Annotated[threading.Lock, Depends(start_lock)]
