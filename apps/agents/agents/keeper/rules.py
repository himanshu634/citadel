"""The Keeper's fixed rules. Pure: no I/O, no model, no clock.

Why: these decisions must not depend on what a model said. Text normalising keys the question
dedupe; the pick order says which gap a review takes first; `conflict` is "sources win" (a claim
the sources contradict never becomes knowledge); `critical_reasons` is the critical rule that
sends a claim to a lead. The decide step and the review run call these.
"""

from __future__ import annotations

import re

from brain.keeper import SourceFacts

from agents.keeper.model import Claim, ClaimKind, Gap

# Gaps a person raised by asking: they come before the ones the Keeper noticed itself.
_ASKED = frozenset({"failed_question", "thumbs_down"})
# Evidence labels that count as a source: the claim rests on something the sources hold.
SOURCE_LABELS = frozenset({"Change", "WorkItem", "Document"})


def normalise(text: str) -> str:
    """Lowercase, collapse whitespace, trim, drop trailing `?.!`: the dedupe key of a question."""
    return re.sub(r"\s+", " ", text).strip().lower().rstrip("?.!").rstrip()


def pick_order(gaps: list[Gap]) -> list[Gap]:
    """Asked gaps first, then most seen, then oldest, then uid. Returns a new list."""
    return sorted(gaps, key=lambda g: (g.kind not in _ASKED, -g.count, g.created_at, g.uid))


def conflict(kind: ClaimKind, value: str | None, facts: SourceFacts) -> str | None:
    """Sources win: what the claim contradicts, or None. Only owner and expert are checked."""
    if kind == "owner" and facts.declared_owners and value not in facts.declared_owners:
        return f"declared owners: {', '.join(facts.declared_owners)}"
    if kind == "expert" and facts.top_expert and facts.top_expert != value:
        return f"top expert: {facts.top_expert}"
    return None


def critical_reasons(
    kind: ClaimKind,
    subject: str,
    about: list[str],
    evidence_labels: dict[str, str],
    earlier: list[Claim],
    high_impact: set[str],
) -> list[str]:
    """Why a claim needs a lead's approval, in a fixed order; empty means it may auto-accept.

    `earlier` is the company's claims; only accepted ones count. `evidence_labels` maps each
    evidence uid to its brain label.
    """
    reasons: list[str] = []
    accepted = [c for c in earlier if c.status == "accepted"]
    if any(c.kind == kind and c.subject == subject for c in accepted) or (
        kind == "decision"
        and any(c.kind == "decision" and set(c.about) & set(about) for c in accepted)
    ):
        reasons.append("replaces_claim")
    if set(about) & high_impact:
        reasons.append("high_impact_system")
    if not SOURCE_LABELS & set(evidence_labels.values()):
        reasons.append("no_source_evidence")
    return reasons
