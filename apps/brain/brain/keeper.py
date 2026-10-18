"""The Keeper's side of the brain: what it reads from brain_<slug> and what it writes there.

Why: the Keeper's ledger (keeper_<slug>) is the source of truth for its claims, but Ask reads the
brain. So accepted claims are projected into brain_<slug> as `Claim` nodes with real `ABOUT` and
`EVIDENCE` edges, which `keeper_notes` and `get_entity` read. Projection MERGEs on uid, so it can
run after every accept and after every build (a rebuild deletes the brain). Ingest never writes
the `Claim` label.

The reads here are the facts the Keeper checks a claim against ("sources win"): which uids exist,
who is declared to own a system and who does most of its work, which systems are high impact (the
top quarter by PageRank), and the noticing queries that open gaps on their own. Every query is a
named file in queries/keeper/, run through `db.run`.

    keeper.project("synthetic", [claim])          # -> uids not projected (subject/evidence gone)
    keeper.notice("synthetic", "stale_owner", 10)  # -> [{subject, about, text}]
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from brain import db, tools

NOTICING_KINDS: tuple[str, ...] = ("stale_owner", "unowned_hot_system")
HOT_DAYS = 90  # unowned_hot_system: activity in the last N days
HIGH_IMPACT_SHARE = 0.25  # the top quarter of systems by PageRank is high impact


@dataclass
class SourceFacts:
    """What the sources say about a claim's subject."""

    exists: bool
    declared_owners: list[str] = field(default_factory=list)  # person and team uids that OWN it
    top_expert: str | None = None  # person uid, row 0 of experts_for_system; None if no System


def evidence(slug: str, uids: list[str]) -> dict[str, str]:
    """uid -> label, for the uids that are nodes in brain_<slug>."""
    if not uids:
        return {}
    rows = db.run(slug, "keeper/evidence", {"uids": list(dict.fromkeys(uids))}, read_only=True)
    return {r["uid"]: r["label"] for r in rows}


def source_facts(slug: str, subject: str) -> SourceFacts:
    rows = db.run(slug, "keeper/source_facts", {"uid": subject}, read_only=True)
    if not rows:
        return SourceFacts(exists=False)
    row = rows[0]
    if row["label"] != "System":
        return SourceFacts(exists=True, declared_owners=list(row["declared_owners"]))
    experts = tools.call(slug, "experts_for_system", system=row["name"], limit=1)
    return SourceFacts(
        exists=True,
        declared_owners=list(row["declared_owners"]),
        top_expert=experts[0].person_uid if experts else None,
    )


def high_impact_systems(slug: str) -> set[str]:
    """Systems in the top quarter by PageRank over the whole graph; ties at the cut are kept.

    Scores are compared rounded to 9 places, so systems the algorithm scores the same up to
    float noise count as a tie."""
    rows = db.run(slug, "keeper/high_impact_systems", read_only=True)
    if not rows:
        return set()
    scores = [(r["uid"], round(r["score"], 9)) for r in rows]
    cut = scores[math.ceil(len(scores) * HIGH_IMPACT_SHARE) - 1][1]
    return {uid for uid, score in scores if score >= cut}


def project(slug: str, claims: list[dict[str, Any]]) -> list[str]:
    """Write accepted claims into brain_<slug> as Claim nodes. Returns the uids of claims that
    were not projected because their subject, or every one of their evidence uids, is missing.

    ABOUT edges go to the claim's subject and its `about` uids; EVIDENCE edges to its evidence
    uids. Uids that are not nodes get no edge.
    """
    wanted = [c["subject"] for c in claims]
    for c in claims:
        wanted += list(c.get("about") or []) + list(c.get("evidence") or [])
    present = evidence(slug, wanted)

    missing: list[str] = []
    rows: list[dict[str, Any]] = []
    for c in claims:
        found = [u for u in dict.fromkeys(c.get("evidence") or []) if u in present]
        if c["subject"] not in present or not found:
            missing.append(c["uid"])
            continue
        about = [u for u in dict.fromkeys([c["subject"], *(c.get("about") or [])]) if u in present]
        rows.append(
            {
                "uid": c["uid"],
                "kind": c["kind"],
                "subject": c["subject"],
                "statement": c["statement"],
                "value": c.get("value"),
                "valid_from": c.get("valid_from"),
                "author": c.get("author"),
                "approved_by": c.get("approved_by"),
                "about": about,
                "evidence": found,
            }
        )
    if rows:  # a write to a graph that does not exist would create it
        db.run(slug, "keeper/project_claim", {"claims": rows}, read_only=False)
    return missing


def retire(slug: str, uid: str, status: str, valid_to: str) -> None:
    """Set a projected claim's status and valid_to (superseded, stale, ...). Nothing is deleted."""
    db.run(
        slug,
        "keeper/retire_claim",
        {"uid": uid, "status": status, "valid_to": valid_to},
        read_only=False,
    )


def notice(slug: str, kind: str, limit: int) -> list[dict[str, Any]]:
    """Gaps the brain shows on its own: rows {subject, about: [uid], text}."""
    if kind not in NOTICING_KINDS:
        raise ValueError(f"unknown noticing kind {kind!r}; known: {', '.join(NOTICING_KINDS)}")
    params: dict[str, Any] = {"limit": limit}
    if kind == "unowned_hot_system":
        params["since_ts"] = tools.since_ts(HOT_DAYS)
    rows = db.run(slug, f"keeper/notice_{kind}", params, read_only=True)
    text = _stale_owner_text if kind == "stale_owner" else _unowned_text
    return [
        {
            "subject": r["subject"],
            "about": [u for u in (r["subject"], r["person_uid"]) if u],
            "text": text(r),
        }
        for r in rows
    ]


def _stale_owner_text(r: dict[str, Any]) -> str:
    owners = ", ".join(r["declared_owners"])
    text = (
        f"{r['system']} is declared owned by {owners}, but most of its changes come from "
        f"{r['login']} ({r['changes']} of {r['total_changes']})."
    )
    if not r["members_known"]:
        text += " The owning team's members are not known, so this can't be confirmed."
    return text


def _unowned_text(r: dict[str, Any]) -> str:
    text = (
        f"{r['system']} has {r['changes']} changes in the last {HOT_DAYS} days and no declared "
        "owner."
    )
    if r["login"]:
        text += f" {r['login']} made the most of them."
    return text
