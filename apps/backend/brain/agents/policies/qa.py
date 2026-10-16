"""QA policy: the system's past fixes are its regressions; fail on the first one the plan and
report do not name, pass when all are covered."""

from __future__ import annotations

import re
from typing import Any

from brain.agents.policies.base import Call, Results, uniq

FIXLIKE = re.compile(r"\b(fix|bug|regress\w*|crash\w*|race|leak|broken|fail\w*)\b", re.I)


def regressions(name: str, results: Results) -> list[dict[str, Any]]:
    """Fix PRs and bug issues in the system, most recent first, without repeats."""
    rows = [
        *results.rows("work_history"),
        *(r for r in results.rows("related_work_items") if name in r.get("systems", [])),
    ]
    seen: dict[str, dict[str, Any]] = {}
    for r in rows:
        if FIXLIKE.search(r.get("title") or "") and r["uid"] not in seen:
            seen[r["uid"]] = r
    return list(seen.values())


def test(context: dict[str, Any], results: Results) -> list[Call] | dict[str, Any]:
    task = context["task"]
    name, system = task.get("system_name"), task.get("system")
    if not results.called("task_timeline"):
        calls: list[Call] = [
            ("task_timeline", {"task": task["uid"]}),
            ("related_work_items", {"text": task["title"]}),
        ]
        if name:
            calls += [
                ("work_history", {"system": name, "limit": 10}),
                ("lessons", {"system": system}),
            ]
        return calls
    found = regressions(name or "", results)
    text = f"{task.get('plan') or ''}\n{task.get('report') or ''}"
    missing = next((r for r in found if r["uid"] not in text), None)
    trail = [a["uid"] for a in results.rows("task_timeline")][-1:]
    out = {
        "task": task["uid"],
        "test_plan": [f"Re-test {r['uid']}: {r['title']}" for r in found[:3]]
        or ["Check the change against its acceptance criteria"],
        "cites": uniq([r["uid"] for r in found[:3]]) or trail,
    }
    if missing:
        return {
            **out,
            "verdict": "failed",
            "regression": missing["uid"],
            "cites": uniq([missing["uid"], *out["cites"]]),
            "reason": f"Plan does not cover past regression {missing['uid']} ({missing['title']}).",
        }
    return {
        **out,
        "verdict": "passed",
        "reason": "Plan and report cover the system's past regressions.",
    }
