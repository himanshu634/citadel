"""Reviewer policy: the system's top two experts, scored relative to the best, each with the
shortest path from them to the system."""

from __future__ import annotations

from typing import Any

from agents.policies.base import Call, Results


def suggest(context: dict[str, Any], results: Results) -> list[Call] | dict[str, Any]:
    task = context["task"]
    name, system = task.get("system_name"), task.get("system")
    if not results.called("experts_for_system"):
        return [("experts_for_system", {"system": name or "", "limit": 3})]
    experts = results.rows("experts_for_system")[:2]
    if experts and not results.called("path_between"):
        return [
            (
                "path_between",
                {"from_uid": e["person_uid"], "to_uid": system, "max_len": 4, "paths": 1},
            )
            for e in experts
        ]
    best = max((e["score"] for e in experts), default=0) or 1
    reviewers = []
    for e in experts:
        paths = results.rows("path_between", from_uid=e["person_uid"])
        path = (
            [n["uid"] for n in paths[0]["nodes"]] if paths else [e["person_uid"], e["system_uid"]]
        )
        reviewers.append(
            {"person": e["person_uid"], "score": round(e["score"] / best, 3), "path": path}
        )
    return {
        "task": task["uid"],
        "reviewers": reviewers,
        "cites": [e["person_uid"] for e in experts],
    }
