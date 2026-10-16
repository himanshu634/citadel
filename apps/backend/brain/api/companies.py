"""Company reads: the list for the rail and one company with its config.

Why: a broken YAML file must show up in the list (so the user can fix it) instead of hiding
the other companies, and status comes from the graph, not from a guess about the files.
"""

from __future__ import annotations

from typing import Annotated

import yaml
from fastapi import APIRouter, Depends, HTTPException

from brain import db, registry
from brain.api.deps import company_slug
from brain.api.models import CompanyDetail, CompanyOut, Status
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


@router.get("/{slug}")
def get_company(slug: Annotated[str, Depends(company_slug)]) -> CompanyDetail:
    try:
        cfg = registry.read(slug)
    except (ValueError, yaml.YAMLError) as exc:  # the file exists but does not validate
        raise HTTPException(status_code=422, detail=registry.describe(exc)) from exc
    return CompanyDetail(**_out(cfg).model_dump(), config=cfg.model_dump(mode="json"))
