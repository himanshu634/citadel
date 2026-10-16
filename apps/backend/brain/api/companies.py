"""Company routes: the list for the rail, one company, and validate/create for the onboarding form.

Why: a broken YAML file must show up in the list (so the user can fix it) instead of hiding
the other companies, and status comes from the graph, not from a guess about the files.
"""

from __future__ import annotations

from typing import Annotated

import yaml
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse
from redis.exceptions import ConnectionError as RedisConnectionError

from brain import db, registry
from brain.api.deps import company_slug
from brain.api.models import CompanyDetail, CompanyOut, Status, ValidateOut
from brain.config import CompanyConfig

router = APIRouter(prefix="/companies", tags=["companies"])


def status_of(slug: str) -> tuple[Status, str | None]:
    """(status, last_synced_at): `ready` once any source was ingested, else `empty`."""
    if not db.graph_exists(slug):
        return "empty", None
    row = db.run(slug, "load/sync_state_latest", read_only=True)[0]
    if not row["sources"]:
        return "empty", None
    return "ready", row["last_synced_at"]


def _out(cfg: CompanyConfig) -> CompanyOut:
    status, last_synced_at = status_of(cfg.slug)
    return CompanyOut(
        slug=cfg.slug,
        name=cfg.name,
        data_permission=cfg.data_permission,
        status=status,
        last_synced_at=last_synced_at,
    )


@router.get("")
def list_companies() -> list[CompanyOut]:
    return [
        CompanyOut(slug=c.slug, name=c.slug, data_permission=None, status="invalid", error=c.error)
        if isinstance(c, registry.InvalidCompany)
        else _out(c)
        for c in registry.list_companies()
    ]


def _slug_taken(draft: dict) -> bool:
    slug = draft.get("slug")
    return isinstance(slug, str) and registry.exists(slug)


@router.post("/validate")
def validate_company(draft: Annotated[dict, Body()]) -> ValidateOut:
    """Check a draft on every form change. Writes nothing."""
    cfg, errors = registry.validate_draft(draft)
    return ValidateOut(
        ok=cfg is not None,
        errors=errors,
        yaml=registry.render_yaml(cfg) if cfg else None,
        slug_taken=_slug_taken(draft),
    )


@router.post("", status_code=201)
def create_company(draft: Annotated[dict, Body()]):
    cfg, errors = registry.validate_draft(draft)
    if cfg is None:  # a plain JSONResponse, so the body is exactly {"detail": [FieldError, ...]}
        return JSONResponse(
            status_code=422, content={"detail": [e.model_dump(mode="json") for e in errors]}
        )
    try:
        registry.write_new(cfg)
    except FileExistsError as exc:
        detail = f"{cfg.slug} is already a company. Pick another name"
        raise HTTPException(status_code=409, detail=detail) from exc
    try:
        out = _out(cfg)
    except RedisConnectionError:  # the file is saved; onboarding must not depend on the graph
        out = CompanyOut(
            slug=cfg.slug, name=cfg.name, data_permission=cfg.data_permission, status="empty"
        )
    return CompanyDetail(**out.model_dump(), config=cfg.model_dump(mode="json"))


@router.get("/{slug}")
def get_company(slug: Annotated[str, Depends(company_slug)]) -> CompanyDetail:
    try:
        cfg = registry.read(slug)
    except (ValueError, yaml.YAMLError) as exc:  # the file exists but does not validate
        raise HTTPException(status_code=422, detail=registry.describe(exc)) from exc
    return CompanyDetail(**_out(cfg).model_dump(), config=cfg.model_dump(mode="json"))
