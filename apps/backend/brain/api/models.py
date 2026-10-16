"""Response models for the HTTP API.

Why: each field the UI reads is named here once; the frontend's types in src/lib/types.ts are
written by hand to match them. `status` is one fixed set so the company rail can switch on it:
`unknown` means FalkorDB could not be asked and no build says otherwise (`graph_reachable` is
then false); it is never guessed as `empty`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from brain.config_diff import ConfigDiff
from brain.jobs import BuildSnapshot, BuildSummary
from brain.registry import FieldError
from brain.tools import PersonActivity, RecentWorkItem, Stat, SystemSummary

Status = Literal["ready", "building", "failed", "empty", "unknown", "invalid"]


class CompanyOut(BaseModel):
    slug: str
    name: str
    data_permission: Literal["public", "synthetic", "own"] | None  # None: the file is invalid
    status: Status
    last_synced_at: str | None = None  # the latest SyncState update, also while building
    error: str | None = None  # the YAML's problem (`invalid`) or the last build's (`failed`)
    build: BuildSummary | None = None  # the company's current or last build
    graph_reachable: bool  # false: FalkorDB did not answer, so the graph part is unknown


class CompanyDetail(CompanyOut):
    config: dict[str, Any]


class BuildIn(BaseModel):
    full: bool = False  # ignore the sync cursors and load everything in the window again


class ValidateOut(BaseModel):
    ok: bool
    errors: list[FieldError]
    yaml: str | None = None  # the file Save would write; only when the draft is valid
    # The draft's slug is valid but already a company, or a former company's graphs or build
    # history are still there (then the detail says to run make reset).
    slug_taken: bool = False
    slug_taken_detail: str | None = None  # the same text a create would answer with (409)


class CompanyRef(BaseModel):
    slug: str
    name: str


class RepoLookup(BaseModel):
    """What the add-a-company dialog shows for a pasted repository. The suggestion (name, slug,
    since) is only made for a public repository that exists."""

    repo: str  # owner/name as GitHub spells it, or as asked when it does not exist
    exists: bool
    private: bool | None = None
    owner_name: str | None = None  # the owner's display name, else its login in words
    name: str | None = None  # suggested company name
    slug: str | None = None  # suggested slug, free to use
    since: str | None = None  # the window start the company would get, an ISO date
    company: CompanyRef | None = None  # the company that already reads this repository
    owner_company: CompanyRef | None = None  # a company that reads another repo of this owner


class OnboardIn(BaseModel):
    repo: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$")
    name: str | None = None  # default: the suggestion
    slug: str | None = None  # default: the suggestion; a taken one given here is a 409


class OnboardOut(BaseModel):
    company: CompanyDetail
    build: BuildSnapshot | None  # None: the company was saved but its build did not start
    build_error: str | None = None


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


class ToolList(BaseModel):
    slug: str
    tools: list[ToolInfo]


class ToolResult(BaseModel):
    slug: str
    tool: str
    rows: list[dict[str, Any]]  # the tool's row model, dumped by alias


class ConfigChange(ConfigDiff):
    """What a Settings save requires (`?dry_run=1`, and the 409 `rebuild_required` detail)."""

    slug: str
