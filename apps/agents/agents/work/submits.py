"""One pydantic model per submit tool: what an agent may write.

Why: an agent ends every run by calling exactly one submit tool. Its input schema is this model
(so Claude sees the field descriptions), the runner validates the input against it, and the job
turns it into named writes on the Keeper's ledger (`queries/ledger/*.cypher`). A write query
takes these fields and nothing else, so no prompt can make an agent write a field it doesn't
own.

Every submit carries `cites`: uids from tool results in this run (ground rule 3). `uids()` lists
every uid the submit refers to, so the runner can check them all against what the run saw.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agents.keeper.model import ClaimKind, RequestOutcome, Verdict

CITES = Field(
    min_length=1,
    description="uids from tool results in this run that support the decision.",
)


class Submit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ClassVar[str]  # the tool name, e.g. "submit_consult"
    description: ClassVar[str]  # one sentence for the model choosing what to call
    subject: ClassVar[str | None] = None  # field that must equal the run's subject uid

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


# --- Keeper -------------------------------------------------------------------------------------

OPTIONAL_CITES = Field(
    default_factory=list,
    description="uids from tool results in this run that support the answer (none when it "
    "cannot be grounded).",
)


def _uid_like(value: str | None) -> list[str]:
    """A claim's value when it names a node (e.g. person:alice), so it is checked like a uid."""
    return [value] if value and ":" in value else []


class SubmitConsult(Submit):
    name: ClassVar[str] = "submit_consult"
    description: ClassVar[str] = (
        "Answer the Keeper's consult on a gap: a draft claim (kind, subject, statement, value) "
        "citing uids you saw, or can_ground false when the graph does not support one."
    )
    subject: ClassVar[str | None] = "consult"

    consult: str = Field(description="uid of the consult being answered.")
    can_ground: bool = Field(description="True when tool results support a claim.")
    kind: ClaimKind | None = Field(None, description="What the claim is (when grounded).")
    subject_uid: str | None = Field(None, description="uid of the node the claim is about.")
    statement: str | None = Field(None, description="The claim in one sentence.")
    value: str | None = Field(
        None, description="The claim's value, e.g. the owner's person uid (optional)."
    )
    cites: list[str] = OPTIONAL_CITES

    @model_validator(mode="after")
    def _grounded(self) -> SubmitConsult:
        if self.can_ground and not (self.kind and self.subject_uid and self.statement):
            raise ValueError("a grounded answer needs kind, subject_uid and statement")
        if self.can_ground and not self.cites:
            raise ValueError("a grounded answer needs at least one cite")
        return self

    def uids(self) -> list[str]:
        """The cites; with a grounded answer also its subject and a uid-like value."""
        if not self.can_ground:
            return list(self.cites)
        subject = [self.subject_uid] if self.subject_uid else []
        return [*self.cites, *subject, *_uid_like(self.value)]


class SubmitKeeperDecision(Submit):
    name: ClassVar[str] = "submit_keeper_decision"
    description: ClassVar[str] = (
        "Decide the gap from the consults' answers: write a claim (kind, subject, statement, "
        "about, cites), ask_archivist (topic) when nobody could ground it and it is about history "
        "older than the brain holds, mark it needs_person when nobody could ground it, or "
        "dismiss it as noise."
    )
    subject: ClassVar[str | None] = "gap"

    gap: str = Field(description="uid of the gap being decided.")
    outcome: Literal["claim", "ask_archivist", "needs_person", "dismiss"]
    kind: ClaimKind | None = Field(None, description="What the claim is (claim).")
    subject_uid: str | None = Field(None, description="uid of the node the claim is about.")
    statement: str | None = Field(None, description="The claim in one sentence (claim).")
    value: str | None = Field(
        None, description="The claim's value, e.g. the owner's person uid (optional)."
    )
    about: list[str] = Field(
        default_factory=list, description="uids of the nodes the claim is about (claim)."
    )
    topic: str | None = Field(
        None, description="What the Archivist should look for in older items (ask_archivist)."
    )
    reason: str = Field(description="One or two sentences: why this outcome.")
    cites: list[str] = OPTIONAL_CITES

    @model_validator(mode="after")
    def _claim(self) -> SubmitKeeperDecision:
        if self.outcome == "ask_archivist" and not (self.topic or "").strip():
            raise ValueError("ask_archivist needs a topic")
        if self.outcome == "claim":
            if not (self.kind and self.subject_uid and self.statement and self.about):
                raise ValueError("a claim needs kind, subject_uid, statement and about")
            if not self.cites:
                raise ValueError("a claim needs at least one cite")
        return self

    def uids(self) -> list[str]:
        """The cites; with a claim also its subject, about and a uid-like value."""
        if self.outcome != "claim":
            return list(self.cites)
        subject = [self.subject_uid] if self.subject_uid else []
        return [*self.cites, *subject, *self.about, *_uid_like(self.value)]


class SubmitFollowUp(Submit):
    name: ClassVar[str] = "submit_follow_up"
    description: ClassVar[str] = (
        "Open the follow-up task for a claim: tell the people an accepted claim concerns, or fix "
        "the source a claim conflicts with."
    )
    subject: ClassVar[str | None] = "claim"

    claim: str = Field(description="uid of the claim the follow-up is for.")
    title: str = Field(max_length=120, description="Short task title.")
    body: str = Field(description="What to do and why, citing the claim's evidence.")


# --- Archivist ----------------------------------------------------------------------------------


class FindIn(BaseModel):
    """One older item to load. Its checks (fetched in this run, quote, evidence in the brain)
    run in the job's apply, so a find that fails them is dropped and logged, not refused here."""

    model_config = ConfigDict(extra="forbid")

    uid: str = Field(description="uid of an item you fetched with archive_fetch in this run.")
    why: str = Field(description="One sentence: why this item answers the request.")
    quote: str = Field(
        description="A passage (at least 20 characters) copied from the item's fetched text "
        "that shows it matches the request."
    )
    verdict: Verdict = Field(
        description="holds: nothing newer in the brain changes it; superseded: a newer item "
        "changed it (give superseded_by); conflicts: it disagrees with a Keeper claim or a "
        "declared owner."
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Brain uids from tool results in this run that connect the item to the "
        "brain and back the verdict.",
    )
    superseded_by: str | None = Field(
        None, description="For superseded: the uid of the newer brain item that changed it."
    )


class SubmitArchiveAnswer(Submit):
    name: ClassVar[str] = "submit_archive_answer"
    description: ClassVar[str] = (
        "Answer the archive request: the older items to load (finds, each with why, a quote, a "
        "verdict and its evidence), a short summary for the asker, and the outcome."
    )
    subject: ClassVar[str | None] = "request"

    request: str = Field(description="uid of the archive request being answered.")
    outcome: RequestOutcome = Field(
        description="found (finds to load), nothing_found, or already_in_brain (what was asked "
        "for is in the brain already)."
    )
    summary: str = Field(description="One or two sentences for the asker.")
    finds: list[FindIn] = Field(default_factory=list, description="Items to load (found).")
    cites: list[str] = OPTIONAL_CITES

    @model_validator(mode="after")
    def _finds(self) -> SubmitArchiveAnswer:
        if self.outcome == "found" and not self.finds:
            raise ValueError("outcome found needs at least one find")
        if self.outcome != "found" and self.finds:
            raise ValueError(f"outcome {self.outcome} takes no finds")
        return self

    def uids(self) -> list[str]:
        """The cites, and each find's uid, evidence and superseded_by (3b: seen in this run)."""
        out = list(self.cites)
        for f in self.finds:
            out += [f.uid, *f.evidence, *([f.superseded_by] if f.superseded_by else [])]
        return out


SUBMITS: dict[str, type[Submit]] = {
    s.name: s for s in [SubmitConsult, SubmitKeeperDecision, SubmitFollowUp, SubmitArchiveAnswer]
}
