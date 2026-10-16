"""Critic policy: same topic and the same stance supersedes; same topic and the opposite stance
(one says no / stop / remove) contradicts."""

from __future__ import annotations

import re
from typing import Any

from agents.policies.base import Call, Results, uniq, words

_NEGATION = re.compile(r"\b(no longer|not|never|stop|remove|revert|drop|disable)\b", re.I)
SAME_TOPIC = 0.5
OPPOSED_TOPIC = 0.3


def _overlap(a: str, b: str) -> float:
    wa, wb = words(a), words(b)
    return len(wa & wb) / len(wa | wb) if wa | wb else 0.0


def check(context: dict[str, Any], results: Results) -> list[Call] | dict[str, Any]:
    d = context["decision"]
    if not results.called("decisions_for_system"):
        return [("decisions_for_system", {"system": s}) for s in d["system_uids"]]
    rows = results.rows("decisions_for_system")
    others = {
        r["uid"]: r
        for r in rows
        if r["uid"] != d["uid"] and (r["valid_from"], r["uid"]) <= (d["valid_from"], d["uid"])
    }
    relations = []
    for o in others.values():
        sim = _overlap(d["summary"], o["summary"])
        opposed = bool(_NEGATION.search(d["summary"])) != bool(_NEGATION.search(o["summary"]))
        if opposed and sim >= OPPOSED_TOPIC:
            rel = "contradicts"
        elif sim >= SAME_TOPIC:
            rel = "supersedes"
        else:
            rel = "unrelated"
        relations.append({"other": o["uid"], "relation": rel, "note": f"overlap {sim:.2f}"})
    cites = uniq(list(others)) or [r["uid"] for r in rows[:1]]
    return {"decision": d["uid"], "relations": relations, "cites": cites}
