"""Keeper policies: pm and qa answer a consult from the work items related to the gap's text; the
Keeper re-reads the first grounded answer's uids and claims it; when no consult could ground a
gap about old history it asks the Archivist, else it says the gap needs a person."""

from __future__ import annotations

import re
from typing import Any

from brain.canonical import system_uid

from agents.policies.base import Call, Results, uniq

CONSULT_ROWS = 3  # related work items a consult answer quotes and cites
# A gap about history older than the window: "old" or "history" as a word (not "golden").
OLD_HISTORY = re.compile(r"\b(old|history)\b", re.IGNORECASE)


def consult(context: dict[str, Any], results: Results) -> list[Call] | dict[str, Any]:
    """pm.consult and qa.consult: a `fact` about the system of the first related work item that
    names one (re-read with get_entity, so the run has seen its uid), else about the first item;
    the statement quotes the first few titles. can_ground False when nothing is related."""
    c, gap = context["consult"], context["gap"]
    if not results.called("related_work_items"):
        return [("related_work_items", {"text": gap.get("text") or ""})]
    rows = results.rows("related_work_items")[:CONSULT_ROWS]
    if not rows:
        return {"consult": c["uid"], "can_ground": False, "cites": []}
    system = next((system_uid(r["systems"][0]) for r in rows if r.get("systems")), None)
    if system and not results.called("get_entity"):
        return [("get_entity", {"uid": system})]
    seen = {r["uid"] for r in results.rows("get_entity")}
    titles = "; ".join(f"'{r['title']}'" for r in rows)
    return {
        "consult": c["uid"],
        "can_ground": True,
        "kind": "fact",
        "subject_uid": system if system in seen else rows[0]["uid"],
        "statement": f"Related work on this: {titles}.",
        "cites": uniq([r["uid"] for r in rows]),
    }


def decide(context: dict[str, Any], results: Results) -> list[Call] | dict[str, Any]:
    """keeper.decide: claim the first grounded consult. Its subject and cites are re-read (the
    consult's search again, and get_entity on each uid), so the claim cites only what this run
    saw; none grounded, or none of its uids found again, gives needs_person."""
    gap = context["gap"]
    consults = context.get("consults") or []
    grounded = [c for c in consults if c.get("can_ground")]
    if not grounded:
        topic = _old_topic(gap.get("text") or "")
        if topic and len(consults) >= 2:
            why = "No consult could ground it, and it asks about older history."
            return {"gap": gap["uid"], "outcome": "ask_archivist", "topic": topic,
                    "reason": why, "cites": []}  # fmt: skip
        return _needs_person(gap, "No consult could ground it in the graph.")
    c = grounded[0]
    if not results.called("get_entity"):
        search: list[Call] = [("related_work_items", {"text": gap.get("text") or ""})]
        return search + [("get_entity", {"uid": u}) for u in uniq([c["subject"], *c["cites"]])]
    rows = [*results.rows("related_work_items"), *results.rows("get_entity")]
    found = {r["uid"] for r in rows}
    cites = [u for u in c["cites"] if u in found]
    if c["subject"] not in found or not cites:
        return _needs_person(gap, f"The {c['role']} answer's evidence is no longer in the graph.")
    value = c.get("value")
    if value and ":" in value and value not in found:
        value = None
    return {
        "gap": gap["uid"],
        "outcome": "claim",
        "kind": c["kind"],
        "subject_uid": c["subject"],
        "statement": c["statement"],
        "value": value,
        "about": [c["subject"]],
        "reason": f"Grounded by {c['role']}: {c['statement']}",
        "cites": cites,
    }


def _old_topic(text: str) -> str | None:
    """What to ask the Archivist about a gap on old history: its words from "old" / "history"
    on ("who decided the old auth system?" -> "old auth system"), since an archive search wants
    every word it is given in the item; None when the gap is not about old history."""
    m = OLD_HISTORY.search(text)
    return " ".join(re.findall(r"\w+", text[m.start() :])) if m else None


def _needs_person(gap: dict[str, Any], reason: str) -> dict[str, Any]:
    return {"gap": gap["uid"], "outcome": "needs_person", "reason": reason, "cites": []}
