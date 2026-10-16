"""One pydantic model per submit tool: what an agent may write.

Why: an agent ends every run by calling exactly one submit tool. Its input schema is this model
(so Claude sees the field descriptions), the runner validates the input against it, and the
store turns it into one or two named writes (`queries/work/*.cypher`). A write query takes these
fields and nothing else, so no prompt can make an agent write a field it doesn't own.

Every submit carries `cites`: uids from tool results in this run (ground rule 3). `uids()` lists
every uid the submit refers to, so the runner can check them all against what the run saw.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from brain.work.model import PRIORITIES

Priority = Literal["P0", "P1", "P2", "P3"]
assert PRIORITIES == Priority.__args__  # one list of priorities

CITES = Field(
    min_length=1,
    description="uids from tool results in this run that support the decision.",
)


class Submit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ClassVar[str]  # the tool name, e.g. "submit_triage"
    description: ClassVar[str]  # one sentence for the model choosing what to call
    subject: ClassVar[str | None] = "task"  # field that must equal the run's subject uid

    cites: list[str] = CITES

    def uids(self) -> list[str]:
        """Every uid this submit refers to (checked against the run's tool results)."""
        return list(self.cites)

    @classmethod
    def tool(cls) -> dict[str, Any]:
        """The Anthropic tool definition."""
        schema = cls.model_json_schema()
        schema.pop("title", None)
        return {"name": cls.name, "description": cls.description, "input_schema": schema}


# --- PM -----------------------------------------------------------------------------------------


class SubmitTriage(Submit):
    name: ClassVar[str] = "submit_triage"
    description: ClassVar[str] = (
        "Triage the open task: either accept it (system, priority, 2-4 acceptance criteria) or "
        "reject it as a duplicate of an earlier task or as out of scope."
    )

    task: str = Field(description="uid of the task being triaged.")
    decision: Literal["triage", "reject"]
    system: str | None = Field(None, description="System uid the task is about (triage).")
    priority: Priority | None = Field(None, description="P0 (most urgent) to P3 (triage).")
    acceptance: list[str] = Field(
        default_factory=list, max_length=4, description="2-4 testable acceptance criteria."
    )
    duplicate_of: str | None = Field(None, description="uid of the earlier task (reject).")
    reason: str = Field(description="One or two sentences: why this decision.")

    @model_validator(mode="after")
    def _shape(self) -> SubmitTriage:
        if self.decision == "triage":
            if not self.system or not self.priority:
                raise ValueError("triage needs system and priority")
            if not 2 <= len(self.acceptance) <= 4:
                raise ValueError("triage needs 2-4 acceptance criteria")
        elif self.duplicate_of == self.task:
            raise ValueError("a task cannot duplicate itself")
        return self

    def uids(self) -> list[str]:
        return [*self.cites, *(u for u in (self.system, self.duplicate_of) if u)]


class SubmitAcceptance(Submit):
    name: ClassVar[str] = "submit_acceptance"
    description: ClassVar[str] = (
        "Accept the finished task, or request changes with the reason (it goes back to the "
        "developer)."
    )

    task: str
    verdict: Literal["accepted", "changes_requested"]
    reason: str = Field(description="Which acceptance criteria are met or missed, and why.")


# --- developer ----------------------------------------------------------------------------------


class SubmitPlan(Submit):
    name: ClassVar[str] = "submit_plan"
    description: ClassVar[str] = (
        "Record the implementation plan for your task (files, risks, who to consult), or yield "
        "the task back to the queue when another in-progress task overlaps too much."
    )

    task: str
    decision: Literal["proceed", "yield"]
    plan: str = Field(description="What to change and how, in a few sentences.")
    planned_files: list[str] = Field(
        default_factory=list, description="Repo paths or globs you will change."
    )
    risks: list[str] = Field(default_factory=list)
    consult: list[str] = Field(default_factory=list, description="Person uids to ask.")

    @model_validator(mode="after")
    def _files(self) -> SubmitPlan:
        if self.decision == "proceed" and not self.planned_files:
            raise ValueError("a plan needs planned_files")
        return self

    def uids(self) -> list[str]:
        return [*self.cites, *self.consult]


class SubmitCompletion(Submit):
    name: ClassVar[str] = "submit_completion"
    description: ClassVar[str] = (
        "Report the task as done. On rework, the report must say how it addresses the reason "
        "it was sent back."
    )

    task: str
    report: str = Field(description="What was done, how each acceptance criterion is covered.")


# --- QA -----------------------------------------------------------------------------------------


class SubmitQa(Submit):
    name: ClassVar[str] = "submit_qa"
    description: ClassVar[str] = (
        "Pass the task, or fail it with the specific past regression its plan does not cover."
    )

    task: str
    verdict: Literal["passed", "failed"]
    test_plan: list[str] = Field(description="The checks, built from past regressions.")
    reason: str
    regression: str | None = Field(
        None, description="uid of the past regression the plan misses (when failing)."
    )

    def uids(self) -> list[str]:
        return [*self.cites, *([self.regression] if self.regression else [])]


# --- DevOps -------------------------------------------------------------------------------------


class ImpactDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system: str = Field(description="System uid.")
    depth: int = Field(ge=0, description="0 for the task's own system, else co-change hops.")


class SubmitRelease(Submit):
    name: ClassVar[str] = "submit_release"
    description: ClassVar[str] = (
        "Ship the release train (name, notes, impacted systems, people to notify), or hold it "
        "for one tick when the blast radius is too large."
    )
    subject: ClassVar[str | None] = "train"

    train: str = Field(description="uid of the release train.")
    decision: Literal["ship", "hold"]
    release_name: str = Field(description="Short release name, e.g. 'Auth hardening'.")
    notes: str
    impacts: list[ImpactDraft] = Field(default_factory=list)
    notify: list[str] = Field(default_factory=list, description="Person uids to notify.")

    def uids(self) -> list[str]:
        return [*self.cites, *(i.system for i in self.impacts), *self.notify]


# --- builder ------------------------------------------------------------------------------------


class DecisionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(description="One line: what was decided.")
    rationale: str = Field(description="Why, from the task's trail and linked work.")
    systems: list[str] = Field(min_length=1, description="System uids it affects.")


class SubmitDecisions(Submit):
    name: ClassVar[str] = "submit_decisions"
    description: ClassVar[str] = (
        "Record 0-2 durable decisions made in this released task. An empty list means nothing "
        "worth recording."
    )

    task: str
    decisions: list[DecisionDraft] = Field(max_length=2)

    def uids(self) -> list[str]:
        return [*self.cites, *(s for d in self.decisions for s in d.systems)]


# --- critic -------------------------------------------------------------------------------------


class Relation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    other: str = Field(description="uid of an earlier current decision.")
    relation: Literal["supersedes", "contradicts", "unrelated"]
    note: str = ""


class SubmitCritique(Submit):
    name: ClassVar[str] = "submit_critique"
    description: ClassVar[str] = (
        "Relate the new decision to each current decision on the same systems: supersedes, "
        "contradicts or unrelated."
    )
    subject: ClassVar[str | None] = "decision"

    decision: str = Field(description="uid of the new decision being checked.")
    relations: list[Relation] = Field(default_factory=list)

    @model_validator(mode="after")
    def _not_self(self) -> SubmitCritique:
        if any(r.other == self.decision for r in self.relations):
            raise ValueError("a decision cannot relate to itself")
        return self

    def uids(self) -> list[str]:
        return [*self.cites, *(r.other for r in self.relations)]


# --- risk ---------------------------------------------------------------------------------------

FindingKind = Literal["bottleneck_person", "single_expert_system", "owner_gap", "first_contact"]


class FindingDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: FindingKind
    subject: str = Field(description="uid of the person or system at risk.")
    summary: str
    cites: list[str] = CITES


class SubmitFindings(Submit):
    name: ClassVar[str] = "submit_findings"
    description: ClassVar[str] = (
        "Record the organisational risks you found (possibly none) in your own memory graph."
    )
    subject: ClassVar[str | None] = None

    findings: list[FindingDraft] = Field(default_factory=list, max_length=10)

    def uids(self) -> list[str]:
        return [*self.cites, *(u for f in self.findings for u in (f.subject, *f.cites))]


# --- reviewer -----------------------------------------------------------------------------------


class ReviewerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    person: str = Field(description="Person uid.")
    score: float = Field(ge=0, le=1)
    path: list[str] = Field(description="uids from the person to the task's system.")


class SubmitReviewers(Submit):
    name: ClassVar[str] = "submit_reviewers"
    description: ClassVar[str] = (
        "Suggest up to two human reviewers, each with the path that justifies them."
    )

    task: str
    reviewers: list[ReviewerDraft] = Field(max_length=2)

    def uids(self) -> list[str]:
        return [*self.cites, *(u for r in self.reviewers for u in (r.person, *r.path))]


SUBMITS: dict[str, type[Submit]] = {
    s.name: s
    for s in [
        SubmitTriage,
        SubmitAcceptance,
        SubmitPlan,
        SubmitCompletion,
        SubmitQa,
        SubmitRelease,
        SubmitDecisions,
        SubmitCritique,
        SubmitFindings,
        SubmitReviewers,
    ]
}
