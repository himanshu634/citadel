"""Test doubles for the agents, shared by the agents tests and the API tests.

- A scripted Claude (`FakeClient` plays back `reply(...)`s) and a one-tool `TOOLSET`, for the
  brain loop without network or database. `settings` pins the Claude settings; import it into a
  test module to make it autouse there.
- A small fake brain (`fake_brain`): canned rows for the graph tools the roles read. Shaped like
  the synthetic company (brain's tests/test_graph.py has the real thing): four systems, a fix PR
  in Auth and in Web app (the regressions QA looks for), Billing and Web app coupled.
"""

from __future__ import annotations

import json
import re
from contextlib import nullcontext
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from anthropic.types.beta import BetaTextBlock, BetaToolUseBlock, BetaUsage
from brain.config import get_settings
from pydantic import BaseModel, Field

from agents import loop
from agents.toolset import Toolset

# --- a scripted Claude ------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    """Pin the Claude settings so a local .env can't change what the tests expect."""
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
    monkeypatch.setenv("ANTHROPIC_EFFORT", "medium")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class SearchParams(BaseModel):
    text: str = Field(description="what to look for")
    limit: int = 10


class Row(BaseModel):
    uid: str
    title: str
    url: str | None = None
    author_uid: str | None = None


@dataclass
class FakeTool:
    name: str
    description: str
    params: type[BaseModel]


ROWS = [
    Row(uid="pr:1", title="Switch sessions to JWT", url="https://x/pr/1", author_uid="person:a"),
    Row(uid="issue:11", title="Session table load"),
]


def run(slug: str, name: str, **params) -> list[BaseModel]:
    assert slug == "synthetic"
    if params["text"] == "boom":
        raise RuntimeError("query failed")
    return ROWS[: params["limit"]]


TOOLSET = Toolset(
    tools={"related_work_items": FakeTool("related_work_items", "Find work items.", SearchParams)},
    run=run,
)


def tool_use(id_: str, name: str, inp: dict) -> BetaToolUseBlock:
    return BetaToolUseBlock(type="tool_use", id=id_, name=name, input=inp)


def text(t: str) -> BetaTextBlock:
    return BetaTextBlock(type="text", text=t)


def reply(*blocks, stop="tool_use", details=None):
    return SimpleNamespace(
        content=list(blocks),
        stop_reason=stop,
        stop_details=details,
        model="claude-haiku-5-5",
        usage=BetaUsage(input_tokens=100, output_tokens=10, cache_read_input_tokens=80),
    )


class FakeClient:
    """Plays back scripted replies and records every request."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs)))  # snapshot, like the wire
        msg = self.replies.pop(0)
        return nullcontext(SimpleNamespace(get_final_message=lambda: msg))


def submit(id_: str, answer: str, sources: list[str], path: list[str] | None = None):
    return tool_use(id_, loop.SUBMIT, {"answer": answer, "sources": sources, "path": path or []})


# --- a fake brain -----------------------------------------------------------------------------

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


def record_run(store, question, client, thread_id=None, saver=None):
    """One run recorded into a chat history store, the way the Ask API drives the Recorder.
    Returns the Answer; its `answer` event goes in with trace id `tr1`."""
    from agents import ask as agent
    from agents.history import Recorder

    rec = Recorder(store, question)
    for event in agent.run_events(
        "synthetic", question, thread_id, client=client, toolset=TOOLSET, checkpointer=saver
    ):
        if isinstance(event, agent.Answer):
            rec.answer(agent.answer_out(event, "tr1"), event.model)
            return event
        rec.on(dict(event))
    raise AssertionError("the run ended without an answer")
