"""A small fake brain for agent tests: canned rows for the graph tools the roles read.

Shaped like the synthetic company (tests/test_graph.py has the real thing): four systems, a fix
PR in Auth and in Web app (the regressions QA looks for), Billing and Web app coupled.
"""

from __future__ import annotations

import re
from typing import Any

SYSTEMS = [
    {
        "system": "Auth",
        "system_uid": "system:Auth",
        "path_rule": "services/auth/**",
        "changes": 10,
        "people": 2,
        "owners": ["identity"],
    },
    {
        "system": "Billing",
        "system_uid": "system:Billing",
        "path_rule": "services/billing/**",
        "changes": 8,
        "people": 2,
        "owners": ["payments"],
    },
    {
        "system": "Web app",
        "system_uid": "system:Web app",
        "path_rule": "web/**",
        "changes": 6,
        "people": 3,
        "owners": ["identity"],
    },
    {
        "system": "Infra",
        "system_uid": "system:Infra",
        "path_rule": "infra/**",
        "changes": 4,
        "people": 1,
        "owners": ["dave"],
    },
]

# uid, number, title, system (newest last)
ITEMS = [
    ("fake:pr:1", 1, "feat(auth): switch sessions to JWT", "Auth"),
    ("fake:pr:2", 2, "fix(auth): refresh token rotation race", "Auth"),
    ("fake:pr:3", 3, "feat(billing): proration for plan changes", "Billing"),
    ("fake:pr:6", 6, "fix(web): login redirect loop", "Web app"),
    ("fake:pr:7", 7, "ci: cache dependencies in pipeline", "Infra"),
    ("fake:pr:10", 10, "refactor(auth): extract token service", "Auth"),
]

EXPERTS = {  # system -> [(login, score, is_declared_owner)]
    "Auth": [("alice", 0.9, True), ("carol", 0.5, True)],
    "Billing": [("bob", 0.8, True), ("erin", 0.4, True)],
    "Web app": [("erin", 0.7, False), ("carol", 0.4, True)],
    "Infra": [("dave", 0.95, True)],
}

COUPLED = {"Billing": ("Web app", 3, 0.6), "Web app": ("Billing", 3, 0.5)}


def _item(uid: str, number: int, title: str, system: str, **extra: Any) -> dict[str, Any]:
    return {
        "uid": uid,
        "kind": "pull_request",
        "number": number,
        "title": title,
        "state": "merged",
        "url": f"https://x/{number}",
        **extra,
    }


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def fake_brain(slug: str, name: str, **p: Any) -> list[dict[str, Any]]:
    """A `graph_run`: (slug, tool name, **params) -> rows."""
    if name == "list_systems":
        return SYSTEMS
    if name == "work_history":
        rows = [
            _item(
                u,
                n,
                t,
                s,
                system_uid=f"system:{s}",
                via="TOUCHES",
                author=None,
                reviewers=[],
                closes=[],
                created_at=None,
                closed_at=None,
            )
            for u, n, t, s in reversed(ITEMS)
            if s == p["system"]
        ]
        return rows[: p.get("limit", 10)]
    if name == "related_work_items":
        want = _words(p["text"])
        rows = [
            _item(u, n, t, s, systems=[s], score=1.0, author=None, closes=[], closed_by=[])
            for u, n, t, s in reversed(ITEMS)
            if want & _words(t)
        ]
        return rows[: p.get("limit", 10)]
    if name == "experts_for_system":
        return [
            {
                "login": login,
                "person_uid": f"person:{login}",
                "score": score,
                "changes": 3,
                "reviews": 1,
                "last_active_ts": None,
                "teams": [],
                "is_declared_owner": owner,
                "evidence": [],
                "declared_owners": [],
                "system_uid": f"system:{p['system']}",
            }
            for login, score, owner in EXPERTS.get(p["system"], [])
        ][: p.get("limit", 10)]
    if name == "impact_of":
        if p["system"] not in COUPLED:
            return []
        other, n, coupling = COUPLED[p["system"]]
        return [
            {
                "system": other,
                "system_uid": f"system:{other}",
                "co_changes": n,
                "coupling": coupling,
                "examples": [],
                "people": [],
                "owners": [],
            }
        ]
    if name == "owners_vs_experts":
        return [
            {
                "system": "Web app",
                "system_uid": "system:Web app",
                "declared_owners": ["identity"],
                "owner_people": ["alice", "carol"],
                "members_known": True,
                "top_contributors": [{"login": "erin", "changes": 5}],
                "total_changes": 6,
            }
        ]
    if name == "path_between":
        person, system = p["from_uid"], p["to_uid"]
        nodes = [
            {"label": "Person", "uid": person, "name": None, "url": None},
            {"label": "System", "uid": system, "name": None, "url": None},
        ]
        return [
            {
                "length": 1,
                "nodes": nodes,
                "rels": [{"type": "TOUCHES", "from": person, "to": system}],
            }
        ]
    if name == "get_entity":
        return []
    raise KeyError(f"fake brain has no tool {name}")
