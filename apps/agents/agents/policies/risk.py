"""Risk policy: owner gaps from owners_vs_experts, single-expert systems (top expert above 70%
of the activity score), and bottleneck people (top expert of two or more systems)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from agents.policies.base import Call, Results, uniq

SINGLE_EXPERT = 0.7
BOTTLENECK = 2


def scan(context: dict[str, Any], results: Results) -> list[Call] | dict[str, Any]:
    if not results.called("list_systems"):
        return [("list_systems", {}), ("owners_vs_experts", {})]
    systems = results.rows("list_systems")
    if systems and not results.called("experts_for_system"):
        return [("experts_for_system", {"system": s["system"], "limit": 5}) for s in systems]
    findings = []
    for g in results.rows("owners_vs_experts"):
        top = ", ".join(c["login"] for c in g.get("top_contributors", [])[:2])
        findings.append(
            {
                "kind": "owner_gap",
                "subject": g["system_uid"],
                "cites": [g["system_uid"]],
                "summary": f"{g['system']}: declared owners "
                f"{', '.join(g['declared_owners'])} are not the people doing "
                f"the work ({top}).",
            }
        )
    tops: dict[str, dict[str, Any]] = {}
    for s in systems:
        experts = results.rows("experts_for_system", system=s["system"])
        if not experts:
            continue
        top, total = experts[0], sum(e["score"] for e in experts)
        tops[s["system_uid"]] = top
        if total and top["score"] / total > SINGLE_EXPERT:
            findings.append(
                {
                    "kind": "single_expert_system",
                    "subject": s["system_uid"],
                    "cites": [s["system_uid"], top["person_uid"]],
                    "summary": f"{s['system']}: {top['login']} holds "
                    f"{top['score'] / total:.0%} of the recent activity.",
                }
            )
    counts = Counter(t["person_uid"] for t in tops.values())
    for person, n in counts.items():
        if n >= BOTTLENECK:
            owned = [s for s, t in tops.items() if t["person_uid"] == person]
            findings.append(
                {
                    "kind": "bottleneck_person",
                    "subject": person,
                    "cites": [person, *owned],
                    "summary": f"{person} is the top expert of {n} systems.",
                }
            )
    cites = uniq([f["subject"] for f in findings]) or [s["system_uid"] for s in systems[:1]]
    return {"findings": findings, "cites": cites}
