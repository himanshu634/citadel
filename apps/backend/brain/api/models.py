"""Response models for the HTTP API.

Why: the frontend types are generated from these, so each field the UI reads is named here once.
`status` is one fixed set so the company rail can switch on it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

Status = Literal["ready", "building", "failed", "empty", "invalid"]


class CompanyOut(BaseModel):
    slug: str
    name: str
    data_permission: Literal["public", "synthetic", "own"] | None  # None: the file is invalid
    status: Status
    last_synced_at: str | None = None
    error: str | None = None
    build: dict | None = None  # BuildSummary arrives with the build routes


class CompanyDetail(CompanyOut):
    config: dict[str, Any]
