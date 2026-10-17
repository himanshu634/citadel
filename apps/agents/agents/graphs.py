"""Names of the graphs the agents own, next to the company graph brain_<slug>.

Why: the company graph is the brain's (`brain.config.graph_name`). The agents keep their own
state in other graphs: the conversation checkpoints (agent_<slug>) and the Keeper's records
(keeper_<slug>). The names live here, apart from `checkpoint.py`, so the permission table
(`acl.py`) can use them without loading langchain. Every name starts from the same slug rules
as the company graph.
"""

from __future__ import annotations

from brain.config import graph_name


def agent_graph_name(slug: str) -> str:
    """Agent conversation checkpoints for one company: agent_<slug>, apart from its brain graph."""
    graph_name(slug)  # same slug rules
    return f"agent_{slug}"


def keeper_graph_name(slug: str) -> str:
    """The Keeper's own records for one company: keeper_<slug>, apart from its brain graph."""
    graph_name(slug)
    return f"keeper_{slug}"
