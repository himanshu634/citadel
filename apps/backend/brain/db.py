"""FalkorDB access.

Why: FalkorDB is the only graph store. This module is the single place that opens a
connection, picks the company graph (`brain_<slug>`) and runs a named query. Everything else
goes through `run()`, so no code can accidentally query the wrong company's graph.
"""

from __future__ import annotations

from functools import cache
from typing import Any

from falkordb import FalkorDB, Graph
from langchain_falkordb.checkpoint import FalkorDBSaver
from redis.exceptions import ResponseError

from brain import queries
from brain.config import agent_graph_name, get_settings, graph_name


@cache
def client() -> FalkorDB:
    s = get_settings()
    return FalkorDB(
        host=s.falkordb_host,
        port=s.falkordb_port,
        username=s.falkordb_username,
        password=s.falkordb_password,
        ssl=s.falkordb_tls,
        # Fail fast on a wrong host/port/TLS setting instead of hanging. No read timeout:
        # big ingestion batches may legitimately take a while.
        socket_connect_timeout=10,
    )


def graph(slug: str) -> Graph:
    return client().select_graph(graph_name(slug))


def checkpointer(slug: str) -> FalkorDBSaver:
    """LangGraph checkpoints for the company's agent threads, in graph agent_<slug>.

    The saver opens its own connection, so it is built here from the same settings. Kept out of
    brain_<slug> so conversation state never mixes with the company graph or its stats.
    """
    s = get_settings()
    return FalkorDBSaver(
        host=s.falkordb_host,
        port=s.falkordb_port,
        username=s.falkordb_username,
        password=s.falkordb_password,
        ssl=s.falkordb_tls,
        database=agent_graph_name(slug),
    )


def ping() -> bool:
    return bool(client().connection.ping())


def graph_exists(slug: str) -> bool:
    return graph_name(slug) in client().list_graphs()


def company_graphs(slug: str) -> list[str]:
    """Which of the company's graphs exist: brain_<slug> and agent_<slug>. A new company may only
    take a slug that has neither, or it would show the old company's data."""
    names = set(client().list_graphs())
    return [n for n in (graph_name(slug), agent_graph_name(slug)) if n in names]


def rows(result) -> list[dict[str, Any]]:
    """Turn a FalkorDB QueryResult into a list of {column: value} dicts."""
    cols = [c[1] if isinstance(c, (list, tuple)) else c for c in result.header]
    return [dict(zip(cols, r, strict=True)) for r in result.result_set]


def run(
    slug: str, name: str, params: dict[str, Any] | None = None, read_only: bool = False
) -> list[dict[str, Any]]:
    """Run the named query (a single statement) against brain_<slug>.

    A read of a graph that does not exist has no rows. FalkorDB answers it with an error, and a
    rebuild can delete the graph between a caller's `graph_exists` check and its read. Any other
    error, such as a broken query on a graph that exists, is raised.
    """
    q = queries.get(name)
    g = graph(slug)
    try:
        result = g.ro_query(q.body, params) if read_only else g.query(q.body, params)
    except ResponseError:
        if read_only and not graph_exists(slug):
            return []
        raise
    return rows(result)


def run_text(slug: str, cypher: str, params: dict[str, Any] | None = None):
    """Run a statement taken from a named query file (e.g. one schema statement).

    Only for text that came from `queries.get(...)`. Never pass user or LLM-built Cypher here.
    """
    return graph(slug).query(cypher, params)


def agent_graph(slug: str) -> Graph:
    return client().select_graph(agent_graph_name(slug))


def run_agent(
    slug: str, name: str, params: dict[str, Any] | None = None, read_only: bool = False
) -> list[dict[str, Any]]:
    """Run the named query against agent_<slug> (the chat history beside the checkpoints).

    A file of several statements (`;`) runs them in order and returns the last one's rows. A
    read of an agent graph that does not exist yet (no chat so far) has no rows.
    """
    g = agent_graph(slug)
    out: list[dict[str, Any]] = []
    for stmt in queries.get(name).statements():
        try:
            out = rows(g.ro_query(stmt, params) if read_only else g.query(stmt, params))
        except ResponseError:
            if read_only and agent_graph_name(slug) not in client().list_graphs():
                return []
            raise
    return out


def delete_graph(slug: str) -> bool:
    if not graph_exists(slug):
        return False
    graph(slug).delete()
    return True


def delete_agent_graph(slug: str) -> bool:
    name = agent_graph_name(slug)
    if name not in client().list_graphs():
        return False
    client().select_graph(name).delete()
    return True
