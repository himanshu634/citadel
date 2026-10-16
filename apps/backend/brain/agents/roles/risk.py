"""Risk watchdog: read-only on the brain; spots people the company can't lose, systems only one
person understands, and owners who no longer do the work. Writes findings to its own memory
graph only (docs/agents.md, "7. Risk watchdog")."""

from __future__ import annotations

from typing import Any

from brain.agents.roles.base import Ctx, Job, Role, Subject, write
from brain.work.store import Row, WorkStore
from brain.work.submits import SubmitFindings

EVERY = 5  # ticks between scans


def _queue(store: WorkStore, ctx: Ctx) -> list[Subject]:
    return [Subject("scan", f"scan:{ctx.tick}", {"tick": ctx.tick})]


def _context(store: WorkStore, ctx: Ctx, s: Subject) -> dict[str, Any]:
    return {"scan": {"tick": ctx.tick}}


def _apply(store: WorkStore, ctx: Ctx, s: Subject, sub: SubmitFindings) -> list[Row]:
    rows = write(
        store, ctx, "memory/write_findings", findings=[f.model_dump() for f in sub.findings]
    )
    return rows or [{"scan": s.uid, "findings": 0}]  # a scan with nothing new still ran


ROLE = Role(
    name="risk",
    db_user="citadel_risk",
    read_tools=(
        "best_first_contact",
        "bottleneck_people",
        "experts_for_system",
        "list_systems",
        "owners_vs_experts",
        "single_expert_systems",
    ),
    jobs=(Job("scan", SubmitFindings, _queue, _apply, _context),),
    every=EVERY,
    summary="Read-only watchdog: key people, single-expert systems, owner gaps.",
)
