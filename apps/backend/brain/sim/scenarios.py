"""Simulation scenarios (docs/agents.md, "Simulations"). Each builds a store and an orchestrator.

The brain is read through the graph tools (`graph_run`, default `brain.tools.call` on
brain_<slug>); the work layer lives in the store. Offline, every role plays its policy
(`agents/policies`); online, every role is Claude.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from brain.agents.policies import offline_client
from brain.agents.toolset import Runner
from brain.sim.orchestrator import ORCHESTRATOR, START, AgentSpec, ClientFor, Orchestrator
from brain.work.memory_store import MemoryStore

# Ten issues for the synthetic company (Auth, Billing, Web app, Infra); 2 and 5 are
# near-duplicates of 1 and 4.
SPRINT_ISSUES: tuple[tuple[str, str], ...] = (
    ("Auth login fails when the refresh token expires", "Users are logged out mid-session."),
    ("Auth login fails when refresh token expires", "Same as before? Users get logged out."),
    ("Billing proration is wrong for annual plans", "Upgrading an annual plan overcharges."),
    ("Web app checkout button unresponsive on Safari", "Clicking pay does nothing on Safari 19."),
    ("Web app checkout button unresponsive in Safari", "Customers report the pay button hangs."),
    ("Infra backups for managed Postgres are not verified", "No restore test has run."),
    ("Auth session cookie lacks SameSite flag", "Security review flagged the cookie."),
    ("Billing invoice PDF shows the wrong currency", "EUR customers see USD on invoices."),
    ("Web app settings page is slow to load", "Takes 4s on a cold cache."),
    ("Infra deploy pipeline is flaky on cache restore", "Builds fail one in five times."),
)

CORE = ("pm", "developer", "developer", "qa", "devops", "builder", "critic", "risk", "reviewer")


def offline(role: str, job: str):
    return offline_client(role, job)


def online(role: str, job: str):
    from brain import llm

    return llm.client()


def model_of(clients: ClientFor) -> str:
    """The model name recorded on each Agent node."""
    from brain.config import get_settings

    return get_settings().anthropic_model if clients is online else "offline-policy"


def agents(roles: Iterable[str]) -> list[AgentSpec]:
    counts: dict[str, int] = {}
    out = []
    for role in roles:
        counts[role] = counts.get(role, 0) + 1
        short = {"developer": "dev"}.get(role, role)
        out.append(AgentSpec(f"agent:{short}-{counts[role]}", role))
    return out


def issues(items: Iterable[tuple[str, str]], prefix: str = "sim") -> list[dict[str, Any]]:
    return [
        {"uid": f"{prefix}:issue:{i}", "title": t, "body": b, "mentions": 0}
        for i, (t, b) in enumerate(items, 1)
    ]


def brain_inputs(slug: str, graph_run: Runner | None) -> dict[str, Any]:
    """What the derive step will compute in phase 2, read through today's graph tools: system
    PageRank (here: share of changes) and CO_CHANGES (from impact_of)."""
    from brain import tools

    run = graph_run or tools.call
    systems = [_plain(r) for r in run(slug, "list_systems", limit=100)]
    total = sum(s["changes"] for s in systems) or 1
    edges = []
    for s in systems:
        for i in run(slug, "impact_of", system=s["system"], limit=5):
            i = _plain(i)
            edges.append((s["system_uid"], i["system_uid"], float(i["co_changes"])))
    return {
        "pagerank": {s["system_uid"]: s["changes"] / total for s in systems},
        "co_changes": edges,
    }


def _plain(row: Any) -> dict[str, Any]:
    return row.model_dump() if hasattr(row, "model_dump") else dict(row)


def _store(slug: str, graph_run: Runner | None, issue_rows=()) -> MemoryStore:
    return MemoryStore(slug, issues=issue_rows, **brain_inputs(slug, graph_run))


def seed_triaged(
    store: MemoryStore, tasks: Iterable[Mapping[str, Any]], now: int = START
) -> list[str]:
    """Put tasks straight into `triaged` (as the PM would), for scenarios that start later."""
    uids = []
    for t in tasks:
        rows = store.write(
            "work/seed_task", "citadel_pm", {"agent": "agent:pm-0", "now": now, "title": t["title"]}
        )
        uid = rows[0]["task"]
        store.write(
            "work/triage_task",
            "citadel_pm",
            {
                "task": uid,
                "agent": "agent:pm-0",
                "now": now,
                "priority": t.get("priority", "P2"),
                "system": t["system"],
                "acceptance": t.get("acceptance", ["It works", "No regressions"]),
                "summary": "Seeded for the scenario",
                "cites": [t["system"]],
            },
        )
        uids.append(uid)
    return uids


def sprint(
    slug: str, *, clients: ClientFor = offline, graph_run: Runner | None = None
) -> Orchestrator:
    """1. Ten issues go from open to released, with every core agent."""
    store = _store(slug, graph_run, issues(SPRINT_ISSUES))
    return Orchestrator(store, agents(CORE), clients, graph_run=graph_run, model=model_of(clients))


RACE_TASKS = (
    {"title": "Rotate signing keys", "system": "system:Auth"},
    {"title": "Retry failed invoice emails", "system": "system:Billing"},
    {"title": "Pin the base image", "system": "system:Infra"},
)


def race(
    slug: str, *, clients: ClientFor = offline, graph_run: Runner | None = None, developers: int = 5
) -> Orchestrator:
    """2. Five developers compete for three triaged tasks in one parallel tick."""
    store = _store(slug, graph_run)
    seed_triaged(store, RACE_TASKS)
    return Orchestrator(
        store,
        agents(["developer"] * developers),
        clients,
        graph_run=graph_run,
        parallel=True,
        steps=(("developer", "plan"),),
        model=model_of(clients),
    )


REGRESSION_TASKS = (
    {"title": "Shorten access token lifetime", "system": "system:Auth"},
    {"title": "Add device names to sessions", "system": "system:Auth"},
    {"title": "Log out all sessions on password change", "system": "system:Auth"},
)


def regression(
    slug: str, *, clients: ClientFor = offline, graph_run: Runner | None = None
) -> Orchestrator:
    """3. QA fails work that misses a known regression, the developer reworks it, and QA learns
    a lesson the second time the same regression is missed."""
    store = _store(slug, graph_run)
    seed_triaged(store, REGRESSION_TASKS)
    steps = (("developer", None), ("qa", "test"))
    return Orchestrator(
        store,
        agents(["developer", "qa"]),
        clients,
        graph_run=graph_run,
        steps=steps,
        model=model_of(clients),
    )


SCENARIOS = {"sprint": sprint, "race": race, "regression": regression}
__all__ = ["ORCHESTRATOR", "SCENARIOS", "race", "regression", "sprint"]
