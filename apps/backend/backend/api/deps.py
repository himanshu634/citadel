"""Shared request dependencies.

Why: every company route is /api/companies/{slug}/..., and the slug picks a graph and a YAML
file. It is resolved here, once, and nowhere else reads it from a body, header or cookie. The
job runner and the lock around starting a build live on the app, so tests can hand in their own.
"""

from __future__ import annotations

import re
import threading

from brain import config
from fastapi import HTTPException, Request

from backend import registry
from backend.jobs import JobRunner


def company_slug(slug: str) -> str:
    """The path slug if it names a company file, else 404."""
    if not re.fullmatch(config.SLUG_RE, slug) or not registry.exists(slug):
        raise HTTPException(status_code=404, detail=f"No company {slug}")
    return slug


def get_runner(request: Request) -> JobRunner:
    return request.app.state.runner


def start_lock(request: Request) -> threading.Lock:
    """Held while a route checks for a running build, writes the YAML and starts a job, so a
    Settings save can never write a file under a build that started a moment earlier."""
    return request.app.state.start_lock
