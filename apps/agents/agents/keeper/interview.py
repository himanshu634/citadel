"""Ask interviews a person: the brain asks about its own gaps and files the reply for a lead.

Why: "ask me questions" is a person offering what they know. The Keeper already lists what the
brain could not answer (gaps); these two tools let the Ask agent read that list and turn a
person's reply into a claim. A reply is a person's word, not a source, so it never becomes
knowledge on its own: every claim filed here waits for a lead (`from_person`, always critical),
and only `decide.approve` (a lead) or `decide.reject` moves it on. This path never projects
into brain_<slug>; it reads the brain and writes the ledger, as the Ask user (`citadel_brain`).

    open_gaps         needs_person first, then open, each in `rules.pick_order`
    record_testimony  checks the subject and cites are brain nodes, moves the gap (if any) from
                      open / needs_person to in_review, writes the pending claim, logs
                      `claim_queued` (actor "ask")

A gap in review with a pending claim is left alone by a review (`review.release_gap`), so the
lead's approve resolves it and a reject reopens it with one more attempt, as for the Keeper's
own claims. Refusals are ValueErrors with a sentence; the toolset hands them to the model.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from brain.keeper import SourceFacts
from pydantic import BaseModel, ConfigDict, Field

from agents.keeper.decide import DEFAULT_BRAIN, EARLIER_LIMIT
from agents.keeper.gaps import WRITER, utc_now
from agents.keeper.model import Claim, ClaimKind, Gap, claim_uid, log_uid
from agents.keeper.rules import conflict, critical_reasons, pick_order
from agents.work.store import WorkStore

FROM_PERSON = "from_person"  # the critical reason every claim filed here carries
ASKABLE = ("needs_person", "open")  # gap statuses a person may answer, in the order offered
READ_LIMIT = 200  # gaps read before ordering
REPLIED = "a person answered in Ask"  # the gap's reason while the claim waits


class _Brain(Protocol):
    """What filing a claim reads from brain_<slug> (`decide.DEFAULT_BRAIN` is the real one)."""

    def evidence(self, slug: str, uids: list[str]) -> dict[str, str]: ...

    def source_facts(self, slug: str, subject: str) -> SourceFacts: ...

    def high_impact_systems(self, slug: str) -> set[str]: ...

    def graph_exists(self, slug: str) -> bool: ...


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OpenGapsParams(_Model):
    limit: int = Field(5, ge=1, le=20, description="Most gaps to return.")


class GapRow(_Model):
    """One gap. `gap` is the ledger id to pass to record_testimony; it is not a brain node, so
    it is never cited (the key has no _uid suffix on purpose). Cite `subject_uid` instead."""

    gap: str
    kind: str
    status: str
    text: str
    subject_uid: str | None = None
    about_uids: list[str] = Field(default_factory=list)
    reason: str | None = None


class RecordTestimonyParams(_Model):
    gap: str | None = Field(
        None, description="The gap from open_gaps this reply answers, or null for none."
    )
    kind: ClaimKind = Field(description="owner, expert, decision, fact or link.")
    subject_uid: str = Field(description="The brain uid the claim is about, e.g. system:billing.")
    statement: str = Field(min_length=1, description="What the person said, as one sentence.")
    value: str | None = Field(
        None, description="For owner or expert: the person's or team's uid. Else null."
    )
    cites: list[str] = Field(
        default_factory=list, description="Brain uids from tool results that back it up."
    )


class TestimonyRow(_Model):
    claim: str  # a ledger id, not a brain node: no _uid suffix, so it is never cited
    status: str
    critical_reasons: list[str]
    conflict: str | None = None  # what the sources say instead, if they disagree


@dataclass(frozen=True)
class _Tool:
    name: str
    description: str
    params: type[BaseModel]


TOOLS: dict[str, _Tool] = {
    "open_gaps": _Tool(
        "open_gaps",
        "List what the brain could not answer and wants a person to tell it (the Keeper's "
        "open gaps), the ones that need a person first. Use when someone asks you to ask them "
        "questions or offers to share what they know.",
        OpenGapsParams,
    ),
    "record_testimony": _Tool(
        "record_testimony",
        "File what the person just told you as a claim for a lead to approve. Only for facts "
        "the person stated in this conversation, never your own inference. Nothing changes in "
        "the brain until a lead approves it.",
        RecordTestimonyParams,
    ),
}


@dataclass
class Interview:
    """The two tools, run against keeper_<slug> (from `ledger`) and brain_<slug>."""

    ledger: Callable[[str], WorkStore]
    brain: _Brain = field(default_factory=lambda: DEFAULT_BRAIN)
    now: Callable[[], str] = utc_now

    def run(self, slug: str, name: str, **params: Any) -> list[BaseModel]:
        if name == "open_gaps":
            return self.open_gaps(slug, **params)
        if name == "record_testimony":
            return [self.record_testimony(slug, **params)]
        raise KeyError(name)

    def open_gaps(self, slug: str, limit: int = 5) -> list[GapRow]:
        rows = self.ledger(slug).read("ledger/gaps", {"statuses": list(ASKABLE),
                                                      "limit": READ_LIMIT})  # fmt: skip
        gaps = [Gap(**r) for r in rows]
        ordered = [g for status in ASKABLE for g in pick_order(gaps) if g.status == status]
        return [
            GapRow(
                gap=g.uid,
                kind=g.kind,
                status=g.status,
                text=g.text,
                subject_uid=g.subject,
                about_uids=[u for u in g.about if u != g.subject],
                reason=g.reason,
            )
            for g in ordered[:limit]
        ]

    def record_testimony(
        self,
        slug: str,
        *,
        gap: str | None,
        kind: ClaimKind,
        subject_uid: str,
        statement: str,
        value: str | None = None,
        cites: list[str] | None = None,
    ) -> TestimonyRow:
        store = self.ledger(slug)
        brain = self.brain
        if not brain.graph_exists(slug):
            raise ValueError("The brain is being rebuilt; ask the person again after the build.")
        cites = list(dict.fromkeys(cites or []))
        found = brain.evidence(slug, [subject_uid, *cites, *([value] if value else [])])
        missing = [u for u in [subject_uid, *cites] if u not in found]
        if missing:
            raise ValueError(
                f"Not nodes in the graph: {', '.join(missing)}. Use uids from tool results."
            )
        if kind in ("owner", "expert") and (not value or value not in found):
            raise ValueError(
                f"An {kind} claim needs value: the uid of a person or team in the graph."
            )

        open_gap = _askable(store, gap) if gap else None
        clash = conflict(kind, value, brain.source_facts(slug, subject_uid))
        earlier = [Claim(**c) for c in store.read(
            "ledger/claims", {"statuses": ["accepted"], "limit": EARLIER_LIMIT})]  # fmt: skip
        about = list(dict.fromkeys([subject_uid, *(open_gap.about if open_gap else [])]))
        labels = {u: found[u] for u in cites}
        high_impact = brain.high_impact_systems(slug)
        reasons = [
            FROM_PERSON,
            *critical_reasons(kind, subject_uid, about, labels, earlier, high_impact),
        ]

        now = self.now()
        if open_gap is not None:
            moved = store.write("ledger/set_gap_status", WRITER, {
                "uid": open_gap.uid, "from": [open_gap.status], "to": "in_review",
                "reason": REPLIED, "now": now, "attempts_inc": 0})  # fmt: skip
            if not moved:
                raise ValueError(f"{gap} changed while you asked; call open_gaps again.")
        claim = Claim(
            uid=claim_uid(),
            kind=kind,
            subject=subject_uid,
            statement=statement.strip(),
            value=value,
            about=about,
            # The person's word is about the subject; keeping it as evidence means projection
            # never takes a reply without cites for a claim whose evidence is gone (stale).
            evidence=list(dict.fromkeys([subject_uid, *cites])),
            critical=True,
            critical_reasons=reasons,
            author="person",
            why=f"{REPLIED}; the sources say {clash}" if clash else REPLIED,
            gap=open_gap.uid if open_gap else None,
            created_at=now,
            updated_at=now,
        )
        try:
            store.write("ledger/write_claim", WRITER, {**claim.model_dump(), "now": now})
        except Exception:
            if open_gap is not None:  # give the gap back rather than strand it in review
                store.write("ledger/set_gap_status", WRITER, {
                    "uid": open_gap.uid, "from": ["in_review"], "to": open_gap.status,
                    "reason": open_gap.reason, "now": now, "attempts_inc": 0})  # fmt: skip
            raise
        store.write("ledger/log", WRITER, {
            "uid": log_uid(now), "at": now, "actor": "ask", "action": "claim_queued",
            "why": ", ".join(reasons), "gap": claim.gap, "claim": claim.uid,
            "evidence": claim.evidence})  # fmt: skip
        return TestimonyRow(
            claim=claim.uid, status=claim.status, critical_reasons=reasons, conflict=clash
        )


def _askable(store: WorkStore, uid: str) -> Gap:
    rows = store.read("ledger/get_gap", {"uid": uid})
    if not rows:
        raise ValueError(f"No gap {uid}; pass a gap from open_gaps, or null.")
    gap = Gap(**rows[0])
    if gap.status not in ASKABLE:
        raise ValueError(f"{uid} is {gap.status.replace('_', ' ')}, not open; pass null.")
    return gap


def keeper_ledger(slug: str) -> WorkStore:
    from agents.keeper.store import KeeperStore

    return KeeperStore(slug)


def ask_tools(
    ledger: Callable[[str], WorkStore] = keeper_ledger, brain: _Brain | None = None
) -> tuple[Mapping[str, _Tool], Callable[..., list[BaseModel]]]:
    """The interview tools and their runner, for `toolset.ask_toolset`."""
    interview = Interview(ledger, brain or DEFAULT_BRAIN)
    return TOOLS, interview.run
