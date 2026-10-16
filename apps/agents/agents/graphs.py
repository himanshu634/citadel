"""Names of the graphs the agents own, next to the company graph brain_<slug>.

Why: the company graph is the brain's (`brain.config.graph_name`). The agents keep their own
state in other graphs: the conversation checkpoints (agent_<slug>), each role's memory
(mem_<slug>_<role>) and what-if forks for simulations (sim_<slug>_<run>). The names live here,
apart from `checkpoint.py`, so the permission table (`acl.py`) can use them without loading
langchain. Every name starts from the same slug rules as the company graph.
"""

from __future__ import annotations

import re

from brain.config import graph_name


def agent_graph_name(slug: str) -> str:
    """Agent conversation checkpoints for one company: agent_<slug>, apart from its brain graph."""
    graph_name(slug)  # same slug rules
    return f"agent_{slug}"


def mem_graph_name(slug: str, role: str) -> str:
    """One agent role's own memory (lessons, findings) for one company: mem_<slug>_<role>."""
    graph_name(slug)
    if not re.fullmatch(r"[a-z]+", role):
        raise ValueError(f"invalid role: {role!r}")
    return f"mem_{slug}_{role}"


def sim_graph_name(slug: str, run: str) -> str:
    """A what-if fork of brain_<slug> for one simulation run: sim_<slug>_<run>."""
    graph_name(slug)
    if not re.fullmatch(r"[a-z0-9][a-z0-9_]*", run):
        raise ValueError(f"invalid run id: {run!r}")
    return f"sim_{slug}_{run}"
