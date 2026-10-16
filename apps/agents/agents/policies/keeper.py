"""Keeper policies: pm and qa answer a consult from the work items related to the gap's text; the
Keeper re-reads the first grounded answer's uids and claims it, or says it needs a person."""

from __future__ import annotations

from typing import Any

from agents.policies.base import Call, Results, uniq

CONSULT_ROWS = 3  # related work items a consult answer quotes and cites


def consult(context: dict[str, Any], results: Results) -> list[Call] | dict[str, Any]:
    """pm.consult and qa.consult: a `fact` about the first related work item, quoting the titles
    of the first few; can_ground False when nothing is related."""
    c, gap = context["consult"], context["gap"]
    if not results.called("related_work_items"):
        return [("related_work_items", {"text": gap.get("text") or ""})]
    rows = results.rows("related_work_items")[:CONSULT_ROWS]
    if not rows:
        return {"consult": c["uid"], "can_ground": False, "cites": []}
    first = rows[0]
    titles = "; ".join(f"'{r['title']}'" for r in rows)
    return {
        "consult": c["uid"],
        "can_ground": True,
        "kind": "fact",
        "subject_uid": first.get("system_uid") or first["uid"],
        "statement": f"Related work on this: {titles}.",
        "cites": uniq([r["uid"] for r in rows]),
    }


def decide(context: dict[str, Any], results: Results) -> list[Call] | dict[str, Any]:
    """keeper.decide: claim the first grounded consult. Its subject and cites are re-read (the
    consult's search again, and get_entity on each uid), so the claim cites only what this run
    saw; none grounded, or none of its uids found again, gives needs_person."""
    gap = context["gap"]
    grounded = [c for c in context.get("consults") or [] if c.get("can_ground")]
    if not grounded:
        return _needs_person(gap, "No consult could ground it in the graph.")
    c = grounded[0]
    if not results.called("get_entity"):
        search: list[Call] = [("related_work_items", {"text": gap.get("text") or ""})]
        return search + [("get_entity", {"uid": u}) for u in uniq([c["subject"], *c["cites"]])]
    rows = [*results.rows("related_work_items"), *results.rows("get_entity")]
    found = {u for r in rows for u in (r.get("uid"), r.get("system_uid")) if u}
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


def _needs_person(gap: dict[str, Any], reason: str) -> dict[str, Any]:
    return {"gap": gap["uid"], "outcome": "needs_person", "reason": reason, "cites": []}
