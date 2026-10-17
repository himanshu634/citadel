"""Which FalkorDB user may read or write which graph (docs/agents.md, "Permissions").

Why: every agent role connects as its own FalkorDB user (ground rule 5), so a role that only
reads the brain cannot change it whatever its prompt says. This table is the one source for
both: the Keeper's stores refuse a write it does not allow, and `setuser_commands` renders the
same table as `ACL SETUSER` lines for FalkorDB.

Graph kinds: `brain` (brain_<slug>), `agent` (agent_<slug>) and `keeper` (keeper_<slug>, the
Keeper's records).
"""

from __future__ import annotations

from brain.config import graph_name

from agents.graphs import agent_graph_name, keeper_graph_name

R, RW = "R", "RW"

PERMISSIONS: dict[str, dict[str, str]] = {
    "citadel_loader": {"brain": RW},
    "citadel_pm": {"brain": R, "keeper": RW},
    "citadel_qa": {"brain": R, "keeper": RW},
    "citadel_brain": {"brain": R, "agent": RW, "keeper": RW},  # Ask opens gaps
    "citadel_keeper": {"brain": RW, "keeper": RW},
}


class Refused(PermissionError):
    """The database user may not do this. FalkorDB answers the same with an ACL error."""


def kind_of(slug: str, graph: str) -> str:
    """The permission key for a graph name of this company."""
    if graph == graph_name(slug):
        return "brain"
    if graph == agent_graph_name(slug):
        return "agent"
    if graph == keeper_graph_name(slug):
        return "keeper"
    raise ValueError(f"{graph!r} is not a graph of company {slug!r}")


def can(db_user: str, slug: str, graph: str, mode: str) -> bool:
    """May `db_user` read ("R") or write ("W") `graph`?"""
    rules = PERMISSIONS.get(db_user, {})
    kind = kind_of(slug, graph)
    return mode in rules.get(kind, "")


def check(db_user: str, slug: str, graph: str, mode: str) -> None:
    if not can(db_user, slug, graph, mode):
        verb = "write" if mode == "W" else "read"
        raise Refused(f"{db_user} may not {verb} {graph}")


def _pattern(slug: str, kind: str) -> str:
    if kind == "brain":
        return graph_name(slug)
    if kind == "agent":
        return agent_graph_name(slug)
    return keeper_graph_name(slug)


def setuser_commands(slug: str, passwords: dict[str, str]) -> list[str]:
    """`ACL SETUSER` lines for every role user on one company (nothing applies them yet).

    Graph-level permissions (`%R~graph`, `%RW~graph`) are a newer FalkorDB feature; test them on
    the falkordb:latest image before relying on them."""
    out = []
    for user, rules in PERMISSIONS.items():
        grants = " ".join(f"%{mode}~{_pattern(slug, kind)}" for kind, mode in rules.items())
        out.append(f"ACL SETUSER {user} on >{passwords[user]} +@all {grants}")
    return out
