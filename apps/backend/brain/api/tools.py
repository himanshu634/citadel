"""Tool routes: list a company's named query tools and run one.

Why: agents and the UI read the graph only through the named tools, so these routes are thin
wrappers over `brain.tools.TOOLS` and `tools.call`. The slug picks the graph; the body is the
tool's params and is validated by the tool's own model (bad values -> 422).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import ValidationError

from brain import db, tools
from brain.api.deps import company_slug
from brain.api.models import ToolInfo

router = APIRouter(prefix="/companies/{slug}/tools", tags=["tools"])

Slug = Annotated[str, Depends(company_slug)]


@router.get("")
def list_tools(slug: Slug) -> list[ToolInfo]:
    return [
        ToolInfo(name=t.name, description=t.description, params_schema=t.params.model_json_schema())
        for t in tools.TOOLS.values()
    ]


@router.post("/{name}")
def call_tool(
    slug: Slug, name: str, params: Annotated[dict[str, Any] | None, Body()] = None
) -> list[dict[str, Any]]:
    tool = tools.TOOLS.get(name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"No tool {name}")
    try:
        tool.params.model_validate(params or {})
    except ValidationError as exc:  # a bad value is the caller's mistake
        detail = exc.errors(include_url=False, include_context=False, include_input=False)
        raise HTTPException(status_code=422, detail=detail) from exc
    rows = tools.call(slug, name, **(params or {})) if db.graph_exists(slug) else []
    return [r.model_dump(mode="json", by_alias=True) for r in rows]
