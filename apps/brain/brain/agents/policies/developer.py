"""Developer policies: plan from the system's path rule, its coupled systems and QA's lessons;
yield when another task changes the same files; report every criterion and every send-back."""

from __future__ import annotations

from typing import Any

from brain.agents.policies.base import Call, Results, first_line, uniq

YIELD_OVER = 0.99  # planned-file overlap with another in-progress task that makes us yield
COUPLED = 0.5  # coupling at which a co-changed system's files join the plan


def _files(name: str, systems: list[dict[str, Any]], impacts: list[dict[str, Any]]) -> list[str]:
    rules = {s["system"]: s.get("path_rule") for s in systems}
    files = [rules.get(name) or f"{name.lower().replace(' ', '-')}/**"]
    for i in impacts[:1]:
        if i.get("coupling", 0) >= COUPLED and rules.get(i["system"]):
            files.append(rules[i["system"]])
    return uniq(files)


def plan(context: dict[str, Any], results: Results) -> list[Call] | dict[str, Any]:
    task = context["task"]
    name, system = task.get("system_name"), task.get("system")
    if not results.called("list_systems"):
        calls: list[Call] = [("list_systems", {})]
        if name:
            calls += [
                ("work_history", {"system": name, "limit": 5}),
                ("experts_for_system", {"system": name, "limit": 3}),
                ("impact_of", {"system": name, "limit": 3}),
                ("lessons", {"system": system}),
            ]
        return calls
    systems = results.rows("list_systems")
    impacts = results.rows("impact_of")
    files = _files(name or "misc", systems, impacts)
    if not results.called("conflicting_tasks"):
        return [("conflicting_tasks", {"task": task["uid"], "planned_files": files})]

    base = {"task": task["uid"], "planned_files": files}
    clash = [c for c in results.rows("conflicting_tasks") if c["overlap"] >= YIELD_OVER]
    if clash:
        c = clash[0]
        return {
            **base,
            "decision": "yield",
            "cites": [c["uid"]],
            "plan": f"{c['uid']} ({c['assignee']}) is changing the same files.",
        }

    history = results.rows("work_history")
    experts = results.rows("experts_for_system")
    lessons = results.rows("lessons")
    text = f"Change {', '.join(files)} for '{task['title']}'."
    if history:
        text += f" Follow the approach of {history[0]['title']} ({history[0]['uid']})."
    for lesson in lessons:
        text += f" Cover regression {lesson.get('regression')}: {lesson['text']}"
    sys_row = next((s for s in systems if s["system_uid"] == system), None)
    return {
        **base,
        "decision": "proceed",
        "plan": text,
        "risks": [
            f"{i['system']} usually changes with it ({i['co_changes']} co-changes)"
            for i in impacts[:2]
        ],
        "consult": [e["person_uid"] for e in experts[:1]],
        "cites": uniq(
            [
                *(h["uid"] for h in history[:2]),
                *(lesson["uid"] for lesson in lessons),
                sys_row["system_uid"] if sys_row else "",
            ]
        )
        or [systems[0]["system_uid"]],
    }


def complete(context: dict[str, Any], results: Results) -> list[Call] | dict[str, Any]:
    task = context["task"]
    if not results.called("task_timeline"):
        return [("task_timeline", {"task": task["uid"]})]
    trail = results.rows("task_timeline")
    back = [a for a in trail if a["kind"] in ("qa_failed", "pm_changes_requested")]
    lines = [f"Done: {first_line(task.get('plan'))}"]
    lines += [f"- {c}: covered" for c in task.get("acceptance", [])]
    lines += [f"Rework: addressed '{a['summary']}'" for a in back]
    planned = [a["uid"] for a in trail if a["kind"] == "planned"][-1:]
    return {
        "task": task["uid"],
        "report": "\n".join(lines),
        "cites": uniq([*planned, *(a["uid"] for a in back)]) or [trail[-1]["uid"]],
    }
