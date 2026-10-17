"""PM policies: consult as `keeper.consult`; a follow-up per claim, citing its evidence."""

from __future__ import annotations

from typing import Any

from agents.policies import keeper
from agents.policies.base import Call, Results, uniq

consult = keeper.consult
TITLE_MAX = 120  # SubmitFollowUp.title


def follow_up(context: dict[str, Any], results: Results) -> list[Call] | dict[str, Any] | None:
    """A follow-up task for the claim: fix the source it conflicts with, or tell the people an
    accepted claim concerns. Cites the claim's evidence, re-read with one round of get_entity (its
    subject when none of the evidence is found). Nothing found: no answer, never empty cites."""
    claim = context["claim"]
    evidence = claim.get("evidence") or []
    if not results.called("get_entity"):
        return [("get_entity", {"uid": u}) for u in uniq([*evidence, claim["subject"]])]
    found = {r["uid"] for r in results.rows("get_entity")}
    cites = [u for u in evidence if u in found] or [u for u in [claim["subject"]] if u in found]
    if not cites:
        return None
    conflict = claim.get("status") == "conflicts_with_source"
    prefix = "Fix the source: " if conflict else "Follow up: "
    title = prefix + claim["statement"]
    if len(title) > TITLE_MAX:
        title = title[: TITLE_MAX - 1] + "…"
    body = (
        f"The sources say otherwise ({claim.get('conflict') or 'see the evidence'}); fix the "
        f"source so it matches: {claim['statement']}"
        if conflict
        else f"The Keeper now holds: {claim['statement']} Tell the people it concerns."
    )
    return {"claim": claim["uid"], "title": title, "body": body, "cites": cites}
