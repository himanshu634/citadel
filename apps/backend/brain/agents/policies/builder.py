"""Builder policy: one decision per released task, on its system, from its plan and report."""

from __future__ import annotations

from typing import Any

from brain.agents.policies.base import Call, Results, first_line, uniq


def record(context: dict[str, Any], results: Results) -> list[Call] | dict[str, Any]:
    task = context["task"]
    name = task.get("system_name")
    if not results.called("task_timeline"):
        calls: list[Call] = [("task_timeline", {"task": task["uid"]})]
        if name:
            calls.append(("work_history", {"system": name, "limit": 3}))
        return calls
    trail = results.rows("task_timeline")
    cites = uniq([a["uid"] for a in trail if a["kind"] in ("planned", "completed", "released")])
    system = next((r["system_uid"] for r in results.rows("work_history")), None)
    base = {"task": task["uid"], "cites": cites or [a["uid"] for a in trail[-1:]]}
    if not system or task["title"].startswith("Risk ("):
        return {**base, "decisions": []}
    rationale = " ".join(
        x for x in (first_line(task.get("plan")), first_line(task.get("report"))) if x
    )
    return {
        **base,
        "decisions": [
            {
                "summary": f"{name}: {task['title']}",
                "rationale": rationale or task["title"],
                "systems": [system],
            },
        ],
    }
