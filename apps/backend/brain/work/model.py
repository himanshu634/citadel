"""The work layer's records: what agents read from and write to the graph.

Why: agents never talk to each other; they hand work over through these records (docs/agents.md,
"Shared model"). Each class is one node label in brain_<slug> (Finding and Lesson live in the
role's own memory graph, mem_<slug>_<role>). Field names are the node property names, so the
FalkorDB store can write `model_dump()` as-is.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Status(StrEnum):
    OPEN = "open"
    TRIAGED = "triaged"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    RELEASED = "released"
    REJECTED = "rejected"
    BLOCKED = "blocked"


class Qa(StrEnum):
    PENDING = "pending"
    TESTING = "testing"
    PASSED = "passed"
    FAILED = "failed"


class Pm(StrEnum):
    PENDING = "pending"
    REVIEWING = "reviewing"
    ACCEPTED = "accepted"
    CHANGES_REQUESTED = "changes_requested"


class ActionKind(StrEnum):
    SEEDED = "seeded"
    TRIAGED = "triaged"
    REJECTED = "rejected"
    CLAIMED = "claimed"
    UNCLAIMED = "unclaimed"  # a developer gave a task back, or a gate claim was dropped
    PLANNED = "planned"
    COMPLETED = "completed"
    QA_STARTED = "qa_started"
    QA_PASSED = "qa_passed"
    QA_FAILED = "qa_failed"
    PM_STARTED = "pm_started"
    PM_ACCEPTED = "pm_accepted"
    PM_CHANGES_REQUESTED = "pm_changes_requested"
    HELD = "held"  # DevOps kept a risky train back for one tick
    RELEASED = "released"
    DECISION_RECORDED = "decision_recorded"
    NO_DECISION = "no_decision"
    DECISION_SUPERSEDED = "decision_superseded"
    CONTRADICTION_FOUND = "contradiction_found"
    CRITIC_CHECKED = "critic_checked"
    REVIEWERS_SUGGESTED = "reviewers_suggested"
    LEASE_EXPIRED = "lease_expired"


PRIORITIES = ("P0", "P1", "P2", "P3")  # P0 is the most urgent


class _Node(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True, validate_default=True)


class Task(_Node):
    uid: str  # task:<n>
    title: str
    body: str = ""
    status: Status = Status.OPEN
    priority: str | None = None  # P0..P3, set by triage
    qa: Qa | None = None
    pm: Pm | None = None
    assignee: str | None = None  # agent uid, e.g. agent:dev-1
    lease_until: int | None = None
    acceptance: list[str] = Field(default_factory=list)
    plan: str | None = None
    planned_files: list[str] = Field(default_factory=list)
    report: str | None = None
    system: str | None = None  # (Task)-[:ABOUT]->(System) uid
    from_issue: str | None = None  # (Task)-[:FROM_ISSUE]->(WorkItem) uid
    from_finding: str | None = (
        None  # Finding uid in mem_<slug>_risk (a string: no cross-graph edge)
    )
    duplicate_of: str | None = None  # (Task)-[:DUPLICATE_OF]->(Task) uid
    last_reason: str | None = None  # why it was last sent back or rejected
    mentions: int = 0  # how often the issue is referenced; feeds the priority formula
    created_ts: int
    updated_ts: int


class Agent(_Node):
    uid: str  # agent:dev-1
    role: str
    db_user: str
    model: str


class Action(_Node):
    uid: str
    kind: ActionKind
    summary: str
    ts: int
    agent: str
    task: str | None = None  # the subject: a Task uid (or a Decision / Release / train uid)
    cites: list[str] = Field(default_factory=list)  # (Action)-[:CITES]->(any node)


class Episode(_Node):
    uid: str
    agent: str
    run_at: int
    tick: int
    input: str  # the job and its subject, e.g. "qa.test task:4"
    summary: str
    tools_called: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)  # (Episode)-[:PRODUCED]->(Action) uids
    stop: str | None = None  # why the run ended without a write, if it did


class Decision(_Node):
    uid: str
    summary: str
    rationale: str
    valid_from: int
    valid_to: int | None = None
    status: str = "current"  # current | superseded | contested
    made_in: str  # (Decision)-[:MADE_IN]->(Task | WorkItem) uid
    systems: list[str] = Field(default_factory=list)  # (Decision)-[:AFFECTS]->(System) uids
    checked_by_critic: bool = False
    supersedes: list[str] = Field(default_factory=list)
    contradicts: list[str] = Field(default_factory=list)


class Impact(_Node):
    system: str
    depth: int


class Release(_Node):
    uid: str
    name: str
    ts: int
    notes: str
    tasks: list[str]  # INCLUDES
    impacts: list[Impact]  # IMPACTS {depth}
    notify: list[str]  # NOTIFIES Person uids


class Finding(_Node):
    """A risk the watchdog saw. Lives in mem_<slug>_risk; cites are uid strings."""

    uid: str
    kind: str
    summary: str
    subject: str
    cites: list[str]
    ts: int


class Lesson(_Node):
    """A failure pattern QA saw twice in one system. Lives in mem_<slug>_qa."""

    uid: str
    system: str
    text: str
    regression: str | None = None
    cites: list[str]
    ts: int


class SuggestedReviewer(_Node):
    task: str
    person: str
    score: float
    path: list[str]
