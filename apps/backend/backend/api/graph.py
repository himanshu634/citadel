"""Graph route: the whole company graph for the Graph page.

Why: the page draws every node at once, so it needs all nodes, links and territories in one
answer (`brain.graph_view`). A company whose graph was never built gets an empty view, not an
error, so the page can show its empty state. Bots are left out unless `bots=true`.
`/graph/node` and `/graph/link` are what one node or one pair of linked nodes stores, read when
the page hovers them (the whole view would be too big with every body and file list in it).
"""

from __future__ import annotations

from typing import Annotated

from brain import db, graph_view
from brain.graph_view import GraphView, LinkDetails, NodeDetails
from fastapi import APIRouter, HTTPException, Query

from backend.api.deps import Slug

router = APIRouter(prefix="/companies/{slug}", tags=["graph"])


@router.get("/graph")
def get_graph(slug: Slug, bots: Annotated[bool, Query()] = False) -> GraphView:
    if not db.graph_exists(slug):
        return graph_view.build(slug, [], [], bots=bots)
    return graph_view.load(slug, bots=bots)


@router.get("/graph/node")
def get_graph_node(slug: Slug, uid: Annotated[str, Query(min_length=1)]) -> NodeDetails:
    details = graph_view.node_details(slug, uid) if db.graph_exists(slug) else None
    if details is None:
        raise HTTPException(404, "This node is no longer in the graph.")
    return details


@router.get("/graph/link")
def get_graph_link(
    slug: Slug, a: Annotated[str, Query(min_length=1)], b: Annotated[str, Query(min_length=1)]
) -> list[LinkDetails]:
    links = graph_view.link_details(slug, a, b) if db.graph_exists(slug) else []
    if not links:
        raise HTTPException(404, "These nodes are no longer linked in the graph.")
    return links
