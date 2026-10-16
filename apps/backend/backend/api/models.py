"""Response models for the HTTP API.

Why: each field the UI reads is named here once; the frontend's types in src/lib/types.ts are
written by hand to match them. `status` is one fixed set so the company rail can switch on it:
`unknown` means FalkorDB could not be asked and no build says otherwise (`graph_reachable` is
then false); it is never guessed as `empty`.
"""

from __future__ import annotations

from typing import Any, Literal

from brain.tools import PersonActivity, RecentWorkItem, Stat, SystemSummary
from pydantic import BaseModel, ConfigDict, Field

from backend.config_diff import ConfigDiff
from backend.jobs import BuildSnapshot, BuildSummary
from backend.registry import FieldError

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


# --- Ask (POST /api/companies/{slug}/ask, answered as Server-Sent Events) ---------------------


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    thread_id: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]{1,64}$")  # a follow-up


class WalkNode(BaseModel):
    uid: str
    label: str  # the graph label: Person, Team, System, WorkItem, Change, Document
    title: str
    url: str | None = None


class WalkRel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    from_: str = Field(alias="from")
    to: str
    type: str  # a stored relationship (AUTHORED) or, when inferred, words (works on)
    inferred: bool = False  # implied by the rows, not stored in the graph
    note: str | None = None  # e.g. "score 0.88"


class AskStart(BaseModel):
    thread_id: str


class AskStep(BaseModel):
    """Claude asked for a tool. `n` numbers the graph steps of one answer; submit_answer (the
    answer check) has none."""

    id: str
    n: int | None
    tool: str
    input: dict[str, Any] | None = None


class AskStepDone(AskStep):
    ms: int | None = None
    count: int | None = None  # rows returned (all of them; `rows` holds the first few)
    error: str | None = None
    rows: list[Any] = []
    nodes: list[WalkNode] = []
    rels: list[WalkRel] = []


class AskSource(BaseModel):
    uid: str
    title: str | None = None
    url: str | None = None
    label: str | None = None
    step: int | None = None  # the step that first returned it


class AskAnswer(BaseModel):
    trace_id: str | None = None  # this turn's trace, for a thumbs (None: it was not kept)
    thread_id: str
    text: str | None  # None when there is no answer (see stop)
    sources: list[AskSource]
    path: list[AskSource]
    stop: str | None  # end_turn ... or refusal, max_tokens, step_limit, stopped, no_answer
    model: str | None = None


class AskError(BaseModel):
    detail: str


class FeedbackIn(BaseModel):
    """A thumbs on one answer; `rating` None takes it back."""

    rating: Literal["up", "down"] | None
    note: str | None = Field(None, max_length=1000)  # what was wrong (or right)


class FeedbackOut(BaseModel):
    trace_id: str
    rating: Literal["up", "down"] | None
    note: str | None = None
