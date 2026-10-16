"""The agents' own graph: conversation checkpoints in agent_<slug>.

Why: an Ask thread is LangGraph state, not company knowledge, so it lives in its own graph next
to brain_<slug> and never mixes with the company graph or its stats. The connection settings
come from `brain.db`, the one place that knows where FalkorDB is.
"""

from __future__ import annotations

from brain import db
from brain.config import graph_name
from langchain_falkordb.checkpoint import FalkorDBSaver

from agents.graphs import agent_graph_name


def checkpointer(slug: str) -> FalkorDBSaver:
    """LangGraph checkpoints for the company's agent threads, in graph agent_<slug>.

    The saver opens its own connection, so it is built from the same settings as `db.client()`.
    """
    return FalkorDBSaver(**db.connection_params(), database=agent_graph_name(slug))


def company_graphs(slug: str) -> list[str]:
    """Which of the company's graphs exist: brain_<slug> and agent_<slug>. A new company may only
    take a slug that has neither, or it would show the old company's data."""
    names = set(db.client().list_graphs())
    return [n for n in (graph_name(slug), agent_graph_name(slug)) if n in names]


def delete_agent_graph(slug: str) -> bool:
    name = agent_graph_name(slug)
    if name not in db.client().list_graphs():
        return False
    db.client().select_graph(name).delete()
    return True
