"""FalkorDB access.

Why: FalkorDB is the only graph store. This module is the single place that opens a
connection, picks the company graph (`brain_<slug>`) and runs a named query. Everything else
goes through `run()`, so no code can accidentally query the wrong company's graph.
"""

from __future__ import annotations

from functools import cache
from typing import Any

from falkordb import FalkorDB, Graph

from brain import queries
from brain.config import get_settings, graph_name


@cache
def client() -> FalkorDB:
    s = get_settings()
    return FalkorDB(
        host=s.falkordb_host,
        port=s.falkordb_port,
        username=s.falkordb_username,
        password=s.falkordb_password,
    )


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
    """Run the named query (a single statement) against brain_<slug>."""
    q = queries.get(name)
    g = graph(slug)
    result = g.ro_query(q.body, params) if read_only else g.query(q.body, params)
    return rows(result)


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
