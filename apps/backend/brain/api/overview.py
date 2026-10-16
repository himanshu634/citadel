"""Overview route: the numbers and lists on a company's overview page.

Why: the page needs a few small answers at once, and each one is already a named tool, so this
route only calls them for one company and puts the results in one response. A company whose graph
was never built gets empty lists, not an error, so the page can show its empty state.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from brain import db, tools
from brain.api.companies import read_config
from brain.api.deps import company_slug
from brain.api.models import Overview

router = APIRouter(prefix="/companies/{slug}", tags=["overview"])

RECENT = 10
SYSTEMS = 8
PEOPLE = 8


@router.get("/overview")
def get_overview(slug: Annotated[str, Depends(company_slug)]) -> Overview:
    cfg = read_config(slug)
    overview = Overview(
        slug=slug,
        name=cfg.name,
        since=cfg.window.since.isoformat(),
        counts=[],
        recent=[],
        systems=[],
        people=[],
    )
    if not db.graph_exists(slug):
        return overview
    overview.counts = [s for s in tools.graph_stats(slug) if s.kind == "node"]
    overview.recent = tools.recent_work_items(slug, limit=RECENT)
    overview.systems = tools.list_systems(slug, limit=SYSTEMS)
    overview.people = tools.people_activity(slug, limit=PEOPLE)
    return overview
