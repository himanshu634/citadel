"""The interface agents and the orchestrator use to read and write the work layer.

Why: ground rule 1 says the graph is the only channel between agents. Every read and write is a
named query, called exactly like `db.run(slug, name, params)`:

    store.read("work/queue_qa", {"now": now})
    store.write("work/claim_task", "citadel_dev", {"task": "task:3", "agent": "agent:dev-1", ...})

A write returns the rows it changed; no rows means its guard did not match ("someone else got
there first" or "not allowed"). A write the database user may not make raises `acl.Refused`.

Two implementations: `MemoryStore` (offline and tests, `memory_store.py`) and, in phase 2, a
FalkorDB store that runs `queries/<name>.cypher` through `db.run` as the role's own user.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from agents.work.moves import MOVES
from agents.work.tools import WORK_TOOLS

Row = dict[str, Any]


class WorkStore(Protocol):
    slug: str

    def read(
        self, name: str, params: Mapping[str, Any] | None = None, *, db_user: str | None = None
    ) -> list[Row]: ...

    def write(self, name: str, db_user: str, params: Mapping[str, Any]) -> list[Row]: ...


# Named queries a store must answer. Phase 2 adds one .cypher file per name.
READS: tuple[str, ...] = (
    "work/get_task",
    "work/untasked_issues",
    "work/untasked_findings",
    "work/queue_pm_triage",
    "work/queue_pm_accept",
    "work/queue_dev_own",
    "work/queue_dev_claimable",
    "work/queue_qa",
    "work/queue_builder",
    "work/queue_critic",
    "work/queue_reviewer",
    "work/get_decision",
    "work/qa_failures",
    "work/actions",
    "work/episodes",
    *(t.query for t in WORK_TOOLS.values()),
    "memory/findings",
)

WRITES: tuple[str, ...] = (
    "work/register_agent",
    "work/seed_task",
    *(f"work/{name}" for name in MOVES),
    "work/expire_leases",
    "work/mark_release_candidates",
    "work/create_release",
    "work/hold_train",
    "work/record_decisions",
    "work/relate_decision",
    "work/suggest_reviewers",
    "work/write_episode",
    "memory/write_episode",
    "memory/write_findings",
    "memory/write_lesson",
)
