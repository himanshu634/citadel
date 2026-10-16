"""Which FalkorDB user may read or write which graph (docs/agents.md, "Permissions").

Why: every agent role connects as its own FalkorDB user (ground rule 5), so a read-only role
such as the Risk watchdog cannot change the brain whatever its prompt says. This table is the
one source for both layers: the in-memory store refuses a write it does not allow, and
`setuser_commands` renders the same table as `ACL SETUSER` lines for FalkorDB.

Graph kinds: `brain` (brain_<slug>), `sim` (sim_<slug>_*), `agent` (agent_<slug>), and
`mem:<role>` (mem_<slug>_<role>); `mem:*` means every role's memory graph.
"""

from __future__ import annotations

from brain.config import agent_graph_name, graph_name

R, RW = "R", "RW"

PERMISSIONS: dict[str, dict[str, str]] = {
    "citadel_loader": {"brain": RW},
    "citadel_orchestrator": {"brain": RW, "sim": RW},
    "citadel_pm": {"brain": RW, "sim": RW, "mem:*": R, "mem:pm": RW},
    "citadel_dev": {"brain": RW, "sim": RW, "mem:dev": RW, "mem:qa": R},
    "citadel_qa": {"brain": RW, "sim": RW, "mem:qa": RW},
    "citadel_devops": {"brain": RW, "sim": RW, "mem:devops": RW},
    "citadel_builder": {"brain": RW, "sim": RW},
    "citadel_critic": {"brain": RW, "sim": RW},
    "citadel_risk": {"brain": R, "sim": R, "mem:risk": RW},
    "citadel_brain": {"brain": R, "sim": R, "agent": RW},
    "citadel_reviewer": {"brain": RW, "sim": RW},
}


class Refused(PermissionError):
    """The database user may not do this. FalkorDB answers the same with an ACL error."""


def kind_of(slug: str, graph: str) -> str:
    """The permission key for a graph name of this company."""
    if graph == graph_name(slug):
        return "brain"
    if graph == agent_graph_name(slug):
        return "agent"
    if graph.startswith(f"sim_{slug}_"):
        return "sim"
    if graph.startswith(f"mem_{slug}_"):
        return f"mem:{graph.removeprefix(f'mem_{slug}_')}"
    raise ValueError(f"{graph!r} is not a graph of company {slug!r}")


def can(db_user: str, slug: str, graph: str, mode: str) -> bool:
    """May `db_user` read ("R") or write ("W") `graph`?"""
    rules = PERMISSIONS.get(db_user, {})
    kind = kind_of(slug, graph)
    grant = rules.get(kind) or (rules.get("mem:*") if kind.startswith("mem:") else None) or ""
    return mode in grant


def check(db_user: str, slug: str, graph: str, mode: str) -> None:
    if not can(db_user, slug, graph, mode):
        verb = "write" if mode == "W" else "read"
        raise Refused(f"{db_user} may not {verb} {graph}")


def _pattern(slug: str, kind: str) -> str:
    if kind == "brain":
        return graph_name(slug)
    if kind == "agent":
        return agent_graph_name(slug)
    if kind == "sim":
        return f"sim_{slug}_*"
    return f"mem_{slug}_{kind.removeprefix('mem:')}"


def setuser_commands(slug: str, passwords: dict[str, str]) -> list[str]:
    """`ACL SETUSER` lines for every role user on one company (phase 2 runs them).

    Graph-level permissions (`%R~graph`, `%RW~graph`) are a newer FalkorDB feature; test them on
    the falkordb:latest image before relying on them."""
    out = []
    for user, rules in PERMISSIONS.items():
        grants = " ".join(f"%{mode}~{_pattern(slug, kind)}" for kind, mode in rules.items())
        out.append(f"ACL SETUSER {user} on >{passwords[user]} +@all {grants}")
    return out


# The agent role each writer user acts as. Task moves check this (moves.MOVES[...].roles), so a
# user can make only its own role's transitions even with RW on the graph.
ROLE_OF: dict[str, str] = {
    "citadel_orchestrator": "orchestrator",
    "citadel_pm": "pm",
    "citadel_dev": "developer",
    "citadel_qa": "qa",
    "citadel_devops": "devops",
    "citadel_builder": "builder",
    "citadel_critic": "critic",
    "citadel_risk": "risk",
    "citadel_brain": "brain",
    "citadel_reviewer": "reviewer",
}
