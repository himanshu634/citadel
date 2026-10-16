"""PM policies: triage by word overlap and system names; accept when the report covers every
acceptance criterion; consult as `keeper.consult`; a follow-up per claim, citing its evidence."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from agents.policies import keeper
from agents.policies.base import Call, Results, uniq, words
from agents.work.memory_store import uid_key

consult = keeper.consult
TITLE_MAX = 120  # SubmitFollowUp.title
DUPLICATE = 0.6  # word overlap with an earlier task's title that makes this one a duplicate
_P0 = re.compile(r"crash|outage|data loss|security|corrupt|leak", re.I)
_P1 = re.compile(r"bug|fail|error|regress|broken|race|wrong|incorrect", re.I)
_P2 = re.compile(r"slow|perf|flaky|timeout|latency", re.I)


def _priority(text: str) -> str:
    for label, pattern in (("P0", _P0), ("P1", _P1), ("P2", _P2)):
        if pattern.search(text):
            return label
    return "P3"


def _earlier(row: dict[str, Any], task: dict[str, Any]) -> bool:
    return (row["created_ts"], uid_key(row["uid"])) < (
        task.get("created_ts", 0),
        uid_key(task["uid"]),
    )


def triage(context: dict[str, Any], results: Results) -> list[Call] | dict[str, Any]:
    task = context["task"]
    title, text = task["title"], f"{task['title']} {task.get('body', '')}"
    if not results.called("list_systems"):
        return [
            ("similar_tasks", {"text": title}),
            ("list_systems", {}),
            ("related_work_items", {"text": title}),
        ]
    systems = results.rows("list_systems")
    base = {"task": task["uid"]}

    dup = next(
        (
            r
            for r in results.rows("similar_tasks")
            if r["uid"] != task["uid"]
            and r["status"] != "rejected"
            and r["score"] >= DUPLICATE
            and _earlier(r, task)
        ),
        None,
    )
    if dup:
        return {
            **base,
            "decision": "reject",
            "duplicate_of": dup["uid"],
            "cites": [dup["uid"]],
            "reason": f"Duplicate of {dup['uid']} ('{dup['title']}').",
        }

    named = sorted(
        (s for s in systems if s["system"].lower() in text.lower()), key=lambda s: -len(s["system"])
    )
    related = results.rows("related_work_items")
    by_name = {s["system"]: s for s in systems}
    votes = Counter(n for r in related for n in r.get("systems", []) if n in by_name)
    system = (
        (named[0] if named else None)
        or (by_name[votes.most_common(1)[0][0]] if votes else None)
        or next((s for s in systems if s["system_uid"] == task.get("system")), None)
    )
    if title.startswith("Risk (") and "owner_gap" not in title:
        cite = system or (systems[0] if systems else None)
        return {
            **base,
            "decision": "reject",
            "cites": [cite["system_uid"]] if cite else [],
            "reason": "Organisational risk the watchdog tracks; no code change to make.",
        }
    if system is None:
        return {
            **base,
            "decision": "reject",
            "cites": [r["uid"] for r in related[:1]],
            "reason": "No system of this codebase fits the task.",
        }
    support = [r["uid"] for r in related if system["system"] in r.get("systems", [])][:2]
    return {
        **base,
        "decision": "triage",
        "system": system["system_uid"],
        "priority": _priority(text),
        "acceptance": [
            f"The problem described in '{title}' no longer happens",
            f"Existing {system['system']} behaviour and tests still pass",
        ],
        "reason": f"New work on {system['system']}"
        + (f", like {', '.join(support)}." if support else "."),
        "cites": uniq([system["system_uid"], *support]),
    }


def covered(criterion: str, report: str) -> bool:
    want = words(criterion)
    return criterion.lower() in report.lower() or (
        bool(want) and len(want & words(report)) / len(want) >= 0.6
    )


def accept(context: dict[str, Any], results: Results) -> list[Call] | dict[str, Any]:
    task = context["task"]
    if not results.called("task_timeline"):
        return [("task_timeline", {"task": task["uid"]})]
    trail = results.rows("task_timeline")
    done = [a["uid"] for a in trail if a["kind"] == "completed"][-1:] or [a["uid"] for a in trail]
    report = task.get("report") or ""
    missing = [c for c in task.get("acceptance", []) if not covered(c, report)]
    if missing:
        return {
            "task": task["uid"],
            "verdict": "changes_requested",
            "cites": done[:1],
            "reason": "The report does not cover: " + "; ".join(missing),
        }
    return {
        "task": task["uid"],
        "verdict": "accepted",
        "cites": done[:1],
        "reason": "Every acceptance criterion is covered in the report.",
    }


def follow_up(context: dict[str, Any], results: Results) -> list[Call] | dict[str, Any]:
    """A follow-up task for the claim: fix the source it conflicts with, or tell the people an
    accepted claim concerns. Cites the claim's evidence, re-read with get_entity (its subject when
    none of the evidence is found)."""
    claim = context["claim"]
    evidence = claim.get("evidence") or []
    if not results.called("get_entity"):
        return [("get_entity", {"uid": u}) for u in uniq([*evidence, claim["subject"]])]
    found = {r["uid"] for r in results.rows("get_entity")}
    cites = [u for u in evidence if u in found] or [u for u in [claim["subject"]] if u in found]
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
