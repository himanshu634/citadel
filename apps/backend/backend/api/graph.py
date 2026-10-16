"""Graph route: the whole company graph for the Graph page.

Why: the page draws every node at once, so it needs all nodes, links and territories in one
answer (`brain.graph_view`). A company whose graph was never built gets an empty view, not an
error, so the page can show its empty state. Bots are left out unless `bots=true`.
"""

from __future__ import annotations

from typing import Annotated

from brain import db, graph_view
from brain.graph_view import GraphView
from fastapi import APIRouter, Depends, Query

from backend.api.deps import company_slug

router = APIRouter(prefix="/companies/{slug}", tags=["graph"])


@router.get("/graph")
def get_graph(
    slug: Annotated[str, Depends(company_slug)], bots: Annotated[bool, Query()] = False
) -> GraphView:
    if not db.graph_exists(slug):
        return graph_view.build(slug, [], [], bots=bots)
    return graph_view.load(slug, bots=bots)
