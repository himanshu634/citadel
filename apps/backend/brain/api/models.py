"""Response models for the HTTP API.

Why: the frontend types are generated from these, so each field the UI reads is named here once.
`status` is one fixed set so the company rail can switch on it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from brain.jobs import BuildSummary
from brain.registry import FieldError
from brain.tools import PersonActivity, RecentWorkItem, Stat, SystemSummary

Status = Literal["ready", "building", "failed", "empty", "invalid"]


class CompanyOut(BaseModel):
    slug: str
    name: str
    data_permission: Literal["public", "synthetic", "own"] | None  # None: the file is invalid
    status: Status
    last_synced_at: str | None = None
    error: str | None = None
    build: BuildSummary | None = None  # the company's current or last build


class CompanyDetail(CompanyOut):
    config: dict[str, Any]


class BuildIn(BaseModel):
    full: bool = False  # ignore the sync cursors and load everything in the window again


class ValidateOut(BaseModel):
    ok: bool
    errors: list[FieldError]
    yaml: str | None = None  # the file Save would write; only when the draft is valid
    slug_taken: bool = False  # true whenever the draft's slug is valid and already a company


class Overview(BaseModel):
    """What a company's overview page draws; every list comes from one named tool."""

    slug: str
    name: str
    since: str  # the YAML's window.since, an ISO date
    counts: list[Stat]  # node kinds only
    recent: list[RecentWorkItem]
    systems: list[SystemSummary]
    people: list[PersonActivity]


class ToolInfo(BaseModel):
    name: str
    description: str
    params_schema: dict[str, Any]
