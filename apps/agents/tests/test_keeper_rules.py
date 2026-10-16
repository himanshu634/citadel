"""The Keeper's fixed rules: text normalising, gap order, sources win, the critical rule."""

from __future__ import annotations

from agents.keeper.model import Claim, Gap
from agents.keeper.rules import conflict, critical_reasons, normalise, pick_order
from brain.keeper import SourceFacts

T1, T2, T3 = "2026-10-17T10:00:00Z", "2026-10-17T10:05:00Z", "2026-10-17T10:10:00Z"


def _gap(uid: str, kind="failed_question", count=1, created_at=T1) -> Gap:
    return Gap(uid=uid, kind=kind, text=uid, count=count, created_at=created_at, updated_at=T3)


def _claim(uid: str, kind="owner", subject="system:billing", about=None, status="accepted"):
    return Claim(
        uid=uid,
        kind=kind,
        subject=subject,
        statement="s",
        about=about or [],
        status=status,
        author="keeper",
        created_at=T1,
        updated_at=T1,
    )


def test_normalise():
    assert normalise("  Who OWNS Billing?? ") == "who owns billing"
    assert normalise("Who\n  owns   billing.!?") == "who owns billing"
    assert normalise("") == ""


def test_pick_order():
    gaps = [
        _gap("gap:a", "stale_owner", count=9),
        _gap("gap:b", "failed_question", count=1, created_at=T2),
        _gap("gap:c", "thumbs_down", count=3, created_at=T3),
        _gap("gap:d", "failed_question", count=3, created_at=T3),
        _gap("gap:e", "unowned_hot_system", count=9, created_at=T1),
        _gap("gap:f", "thumbs_down", count=3, created_at=T1),
        _gap("gap:g", "thumbs_down", count=3, created_at=T1),
    ]
    order = [g.uid for g in pick_order(gaps)]
    # questions first, count desc, then oldest, then uid; then the noticed gaps the same way
    assert order == ["gap:f", "gap:g", "gap:c", "gap:d", "gap:b", "gap:a", "gap:e"]
    assert [g.uid for g in gaps][0] == "gap:a"  # the input list is not reordered


def test_conflict_owner():
    facts = SourceFacts(True, ["person:alex"], None)
    assert conflict("owner", "person:dana", facts) == "declared owners: person:alex"
    assert conflict("owner", "person:alex", facts) is None
    assert conflict("owner", "person:dana", SourceFacts(True, [], None)) is None
    two = SourceFacts(True, ["person:alex", "team:core"], None)
    assert conflict("owner", "person:dana", two) == "declared owners: person:alex, team:core"
    assert conflict("owner", None, facts) == "declared owners: person:alex"


def test_conflict_expert_and_other_kinds():
    facts = SourceFacts(True, [], "person:eve")
    assert conflict("expert", "person:dana", facts) == "top expert: person:eve"
    assert conflict("expert", "person:eve", facts) is None
    assert conflict("expert", "person:dana", SourceFacts(True, [], None)) is None
    declared = SourceFacts(True, ["person:alex"], "person:eve")
    for kind in ("fact", "decision", "link"):
        assert conflict(kind, "person:dana", declared) is None
    # the owner check does not read the expert, and the expert check does not read the owners
    assert conflict("owner", "person:alex", declared) is None
    assert conflict("expert", "person:eve", declared) is None


SRC = {"change:1": "Change"}


def test_critical_reasons_each():
    # replaces_claim: same kind and subject
    earlier = [_claim("claim:1", "owner", "system:billing")]
    assert critical_reasons("owner", "system:billing", [], SRC, earlier, set()) == [
        "replaces_claim"
    ]
    # a different subject, or a claim that is not accepted, replaces nothing
    assert critical_reasons("owner", "system:auth", [], SRC, earlier, set()) == []
    pending = [_claim("claim:2", "owner", "system:billing", status="pending_approval")]
    assert critical_reasons("owner", "system:billing", [], SRC, pending, set()) == []
    # a decision replaces any accepted decision about one of its systems
    decisions = [_claim("claim:3", "decision", "decision:x", about=["system:billing"])]
    assert critical_reasons(
        "decision", "decision:y", ["system:auth", "system:billing"], SRC, decisions, set()
    ) == ["replaces_claim"]
    assert critical_reasons("decision", "decision:y", ["system:auth"], SRC, decisions, set()) == []
    # ... but an owner claim is not a decision, so about alone does not replace it
    assert critical_reasons("owner", "system:auth", ["system:billing"], SRC, decisions, set()) == []

    # high_impact_system
    assert critical_reasons(
        "fact", "system:auth", ["system:auth", "system:billing"], SRC, [], {"system:billing"}
    ) == ["high_impact_system"]

    # no_source_evidence: only a Person/System/Claim, or nothing at all
    assert critical_reasons("fact", "system:auth", [], {}, [], set()) == ["no_source_evidence"]
    people = {"person:alex": "Person", "system:auth": "System"}
    assert critical_reasons("fact", "system:auth", [], people, [], set()) == ["no_source_evidence"]
    for label in ("Change", "WorkItem", "Document"):
        assert critical_reasons("fact", "system:auth", [], {"u": label}, [], set()) == []

    # none
    assert (
        critical_reasons(
            "owner", "system:auth", ["system:auth"], {"wi:1": "WorkItem"}, earlier, {"system:x"}
        )
        == []
    )


def test_critical_reasons_order_and_all_three():
    earlier = [_claim("claim:1", "owner", "system:billing")]
    assert critical_reasons(
        "owner", "system:billing", ["system:billing"], {}, earlier, {"system:billing"}
    ) == ["replaces_claim", "high_impact_system", "no_source_evidence"]
