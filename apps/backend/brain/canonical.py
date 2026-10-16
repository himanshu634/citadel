"""Canonical records: the contract between source adapters and the loader.

Why: adapters know about one tool (GitHub, Slack exports, a docs folder); the loader knows only
these models. Any source that can produce these records can be ingested without touching the
loader, the schema or the queries.

Identity rules:
- Every record has a stable `uid`. Re-ingesting the same thing gives the same uid, so the
  loader can MERGE on it.
- People, teams and systems get source-free uids (`person:<login>`, `team:<name>`,
  `system:<name>`), so the same login seen in GitHub and in a JSONL export is one node.
- No email addresses anywhere: people are identified by login / configured handle.
- `WorkItem.kind` covers PRs, issues, tickets and chat threads, so Jira/Linear/Slack data fits.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --- uid helpers ------------------------------------------------------------------------------


def person_uid(login: str) -> str:
    return f"person:{login.lower()}"


def team_uid(name: str) -> str:
    return f"team:{name.lower()}"


def system_uid(name: str) -> str:
    return f"system:{name}"


def to_utc(dt: datetime | None) -> datetime | None:
    """Treat naive datetimes as UTC and convert aware ones to UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


# --- base -------------------------------------------------------------------------------------


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uid: str = ""  # Person/Team/System derive it; every other record must set it
    source: str = "unknown"  # e.g. "github", "canonical_jsonl", "local_docs"
    url: str | None = None  # where a human can see the original (used for citations)

    def changed_at(self) -> datetime | None:
        """Latest timestamp on the record; used by incremental ingest. None = always load."""
        return None

    @model_validator(mode="after")
    def _uid_required(self):
        if not self.uid:
            raise ValueError(f"{type(self).__name__} needs a uid")
        return self


def _latest(*dts: datetime | None) -> datetime | None:
    present = [to_utc(d) for d in dts if d is not None]
    return max(present) if present else None


# --- nodes ------------------------------------------------------------------------------------


class Person(Record):
    login: str
    display_name: str | None = None
    is_bot: bool = False  # normalize sets it from the config (people.bots, "[bot]" suffix)

    @field_validator("login")
    @classmethod
    def _not_an_email(cls, v: str) -> str:
        if "@" in v:
            raise ValueError("login must be a handle, not an email address")
        return v

    @model_validator(mode="before")
    @classmethod
    def _derive_uid(cls, data: dict) -> dict:
        if isinstance(data, dict) and not data.get("uid") and data.get("login"):
            data = {**data, "uid": person_uid(data["login"])}
        return data


class Team(Record):
    name: str

    @model_validator(mode="before")
    @classmethod
    def _derive_uid(cls, data: dict) -> dict:
        if isinstance(data, dict) and not data.get("uid") and data.get("name"):
            data = {**data, "uid": team_uid(data["name"])}
        return data


class System(Record):
    name: str
    path_rule: str | None = None  # the config rule that produced it, e.g. "src/index/**"

    @model_validator(mode="before")
    @classmethod
    def _derive_uid(cls, data: dict) -> dict:
        if isinstance(data, dict) and not data.get("uid") and data.get("name"):
            data = {**data, "uid": system_uid(data["name"])}
        return data


ChangeKind = Literal["feat", "fix", "perf", "ci", "build", "docs", "refactor", "other"]


class Change(Record):
    """A commit (or any unit of code change)."""

    sha: str
    date: datetime
    author_login: str | None = None
    subject: str
    kind: ChangeKind | None = None  # normalize parses it from the conventional-commit prefix
    files: list[str] = []  # repo-relative paths touched
    systems: list[str] = []  # explicit system names (for sources without file paths)
    # Filled by normalize: system name -> files in that system. Becomes TOUCHES {files}.
    touches: dict[str, list[str]] = {}

    def changed_at(self) -> datetime | None:
        return to_utc(self.date)


WorkItemKind = Literal["pull_request", "issue", "ticket", "thread"]


class WorkItem(Record):
    """A PR, issue, ticket or discussion thread."""

    kind: WorkItemKind
    number: int | None = None
    title: str
    body: str = ""
    state: str  # source-specific: open / closed / merged / done ...
    created_at: datetime
    updated_at: datetime | None = None
    closed_at: datetime | None = None
    merged_at: datetime | None = None
    author_login: str | None = None
    labels: list[str] = []
    container: str | None = None  # repo, Jira project, Slack channel ...

    def changed_at(self) -> datetime | None:
        return _latest(self.created_at, self.updated_at, self.closed_at, self.merged_at)


class Document(Record):
    path: str
    title: str
    body: str = ""
    author_login: str | None = None
    updated_at: datetime | None = None

    def changed_at(self) -> datetime | None:
        return to_utc(self.updated_at)


# --- facts that become relationships (plus a Chunk for comment text) ---------------------------


class Review(Record):
    work_item_uid: str
    reviewer_login: str
    state: str  # APPROVED / CHANGES_REQUESTED / COMMENTED ...
    submitted_at: datetime

    def changed_at(self) -> datetime | None:
        return to_utc(self.submitted_at)


class Comment(Record):
    """Becomes (Person)-[:COMMENTED_ON]->(WorkItem) and a text Chunk FROM the work item."""

    work_item_uid: str
    author_login: str
    created_at: datetime
    body: str

    def changed_at(self) -> datetime | None:
        return to_utc(self.created_at)


class Ownership(Record):
    """Declared ownership, e.g. a CODEOWNERS line. Becomes (Team|Person)-[:OWNS]->(System)."""

    owner_kind: Literal["person", "team"]
    owner: str  # login or team name
    pattern: str  # the path pattern as written, e.g. "/src/index/"
    systems: list[str] = []  # explicit; if empty, normalize maps the pattern via path rules


LinkRel = Literal["CLOSES", "MENTIONS", "PART_OF", "MEMBER_OF"]
LinkLabel = Literal["Person", "Team", "System", "Change", "WorkItem", "Document"]

# The only (rel, from, to) combinations the graph model allows. Each one has its own load query
# (relationship types and labels cannot be Cypher parameters), see loader.LINK_QUERIES.
ALLOWED_LINKS: set[tuple[str, str, str]] = {
    ("CLOSES", "WorkItem", "WorkItem"),
    ("PART_OF", "Change", "WorkItem"),
    ("MEMBER_OF", "Person", "Team"),
    ("MENTIONS", "WorkItem", "WorkItem"),
    ("MENTIONS", "WorkItem", "System"),
    ("MENTIONS", "Document", "WorkItem"),
    ("MENTIONS", "Document", "System"),
}


class Link(Record):
    """A typed edge between two records that already have uids."""

    uid: str = ""  # derived from the endpoints when not given
    rel: LinkRel
    from_uid: str
    from_label: LinkLabel
    to_uid: str
    to_label: LinkLabel
    props: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _derive_uid(cls, data: dict) -> dict:
        if isinstance(data, dict) and not data.get("uid"):
            uid = f"link:{data.get('rel')}:{data.get('from_uid')}->{data.get('to_uid')}"
            data = {**data, "uid": uid}
        return data

    @model_validator(mode="after")
    def _allowed(self):
        if (self.rel, self.from_label, self.to_label) not in ALLOWED_LINKS:
            raise ValueError(
                f"link {self.rel} from {self.from_label} to {self.to_label} is not in the "
                "graph model (see canonical.ALLOWED_LINKS)"
            )
        return self


CanonicalRecord = (
    Person | Team | System | Change | WorkItem | Document | Review | Comment | Ownership | Link
)
