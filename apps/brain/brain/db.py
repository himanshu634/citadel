"""FalkorDB access.

Why: FalkorDB is the only graph store. This module is the single place that opens a
connection, picks the company graph (`brain_<slug>`) and runs a named query. Everything else
goes through `run()`, so no code can accidentally query the wrong company's graph.
"""

from __future__ import annotations

from functools import cache
from typing import Any

from falkordb import FalkorDB, Graph
from redis.exceptions import ResponseError

from brain import queries
from brain.config import get_settings, graph_name


def connection_params() -> dict[str, Any]:
    """Where FalkorDB is and how to log in, from the settings. `client()` connects with these;
    a library that opens its own connection (the agents' checkpointer) gets the same ones."""
    s = get_settings()
    return {
        "host": s.falkordb_host,
        "port": s.falkordb_port,
        "username": s.falkordb_username,
        "password": s.falkordb_password,
        "ssl": s.falkordb_tls,
    }


@cache
def client() -> FalkorDB:
    # Fail fast on a wrong host/port/TLS setting instead of hanging. No read timeout:
    # big ingestion batches may legitimately take a while.
    return FalkorDB(**connection_params(), socket_connect_timeout=10)


def graph(slug: str) -> Graph:
    return client().select_graph(graph_name(slug))


def ping() -> bool:
    return bool(client().connection.ping())


def graph_exists(slug: str) -> bool:
    return graph_name(slug) in client().list_graphs()


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


def explain(slug: str, name: str, params: dict[str, Any] | None = None) -> list[str]:
    """The execution plan FalkorDB would use for the named query, one operation per line
    (e.g. "Node By Index Scan | (n:Node)"), without running it. Tests use it to check that a
    lookup is index-backed and not an "All Node Scan"."""
    return list(graph(slug).explain(queries.get(name).body, params))


def run_text(slug: str, cypher: str, params: dict[str, Any] | None = None):
    """Run a statement taken from a named query file (e.g. one schema statement).

    Only for text that came from `queries.get(...)`. Never pass user or LLM-built Cypher here.
    """
    return graph(slug).query(cypher, params)


def delete_graph(slug: str) -> bool:
    if not graph_exists(slug):
        return False
    graph(slug).delete()
    return True
