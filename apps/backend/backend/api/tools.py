"""Tool routes: list a company's named query tools and run one.

Why: agents and the UI read the graph only through the named tools, so these routes are thin
wrappers over `brain.tools.TOOLS` and `tools.call`. The slug picks the graph; the body is the
tool's params and is validated by the tool's own model (bad values -> 422; unknown keys are
dropped). A tool that needs embeddings it cannot use (off, nothing embedded yet, or embedded
with another model) is a 503 with the reason. Both responses carry the slug they were built for.
"""

from __future__ import annotations

from typing import Annotated, Any

from brain import db, tools
from brain.cypher import CypherError
from brain.embeddings import EmbeddingUnavailable
from fastapi import APIRouter, Body, HTTPException
from pydantic import ValidationError

from backend.api.deps import Slug
from backend.api.models import ToolInfo, ToolList, ToolResult

router = APIRouter(prefix="/companies/{slug}/tools", tags=["tools"])


@router.get("")
def list_tools(slug: Slug) -> ToolList:
    return ToolList(
        slug=slug,
        tools=[
            ToolInfo(
                name=t.name, description=t.description, params_schema=t.params.model_json_schema()
            )
            for t in tools.TOOLS.values()
        ],
    )


@router.post("/{name}")
def call_tool(
    slug: Slug, name: str, params: Annotated[dict[str, Any] | None, Body()] = None
) -> ToolResult:
    tool = tools.TOOLS.get(name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"No tool {name}")
    try:
        validated = tool.params.model_validate(params or {})
    except ValidationError as exc:  # a bad value is the caller's mistake
        detail = exc.errors(include_url=False, include_context=False, include_input=False)
        raise HTTPException(status_code=422, detail=detail) from exc
    # Only the model's fields go on: other body keys (e.g. "slug") are dropped, not passed along.
    try:
        rows = tools.call(slug, name, **validated.model_dump()) if db.graph_exists(slug) else []
    except EmbeddingUnavailable as exc:  # semantic search without usable vectors: say why
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except CypherError as exc:  # run_cypher: a refused or broken query is the caller's mistake
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ToolResult(
        slug=slug, tool=name, rows=[r.model_dump(mode="json", by_alias=True) for r in rows]
    )
