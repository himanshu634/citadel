"""The agents' own graph: conversation checkpoints in agent_<slug>.

Why: an Ask thread is LangGraph state, not company knowledge, so it lives in its own graph next
to brain_<slug> and never mixes with the company graph or its stats. The connection settings
come from `brain.db`, the one place that knows where FalkorDB is.
"""

from __future__ import annotations

from typing import Any

from brain import db, queries
from brain.config import graph_name
from falkordb import Graph
from langchain_falkordb.checkpoint import FalkorDBSaver
from redis.exceptions import ResponseError

from agents.graphs import agent_graph_name


def checkpointer(slug: str) -> FalkorDBSaver:
    """LangGraph checkpoints for the company's agent threads, in graph agent_<slug>.

    The saver opens its own connection, so it is built from the same settings as `db.client()`.
    """
    return FalkorDBSaver(**db.connection_params(), database=agent_graph_name(slug))


def graph(slug: str) -> Graph:
    return db.client().select_graph(agent_graph_name(slug))


def run(
    slug: str, name: str, params: dict[str, Any] | None = None, read_only: bool = False
) -> list[dict[str, Any]]:
    """Run the named query against agent_<slug> (the chat history beside the checkpoints, see
    `history.py`), like `db.run` does for brain_<slug>.

    A file of several statements (`;`) runs them in order and returns the last one's rows. A
    read of an agent graph that does not exist yet (no chat so far) has no rows.
    """
    g = graph(slug)
    out: list[dict[str, Any]] = []
    for stmt in queries.get(name).statements():
        try:
            out = db.rows(g.ro_query(stmt, params) if read_only else g.query(stmt, params))
        except ResponseError:
            if read_only and agent_graph_name(slug) not in db.client().list_graphs():
                return []
            raise
    return out


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
