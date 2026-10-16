"""Agent roles. `ROLES` is the registry; each module defines one `ROLE`.

Orchestrator order (docs/agents.md, "Orchestrator"): PM triage -> developers -> QA -> PM
accept -> DevOps -> Builder -> Critic -> Risk -> Reviewer. The Keeper (and the pm/qa consult
and follow-up jobs) runs in its own review run, not in the simulation's ticks.
"""

from __future__ import annotations

from agents.roles import (
    brain,
    builder,
    critic,
    developer,
    devops,
    keeper,
    pm,
    qa,
    reviewer,
    risk,
)
from agents.roles.base import Ctx, Job, Role, Subject

ROLES: dict[str, Role] = {
    r.name: r
    for r in (
        pm.ROLE,
        developer.ROLE,
        qa.ROLE,
        devops.ROLE,
        builder.ROLE,
        critic.ROLE,
        risk.ROLE,
        brain.ROLE,
        reviewer.ROLE,
        keeper.ROLE,
    )
}

__all__ = ["ROLES", "Ctx", "Job", "Role", "Subject"]
