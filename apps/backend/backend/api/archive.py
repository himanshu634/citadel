"""Archive route: the Archivist's requests and what each found.

Why: the Archivist (`agents/archivist`) searches older history for Ask and for the Keeper, and
writes every request and find to the Keeper's ledger (keeper_<slug>). This reads them back.

- GET .../archive/requests?limit= : the latest `limit` requests, most recently updated first,
  each with its finds (verdict, quote, evidence). Two reads, whatever the limit.
"""

from __future__ import annotations

from typing import Annotated

from agents.keeper.model import ArchiveFind, ArchiveRequest
from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.api.deps import Slug
from backend.api.keeper import Keeper

router = APIRouter(prefix="/companies/{slug}/archive", tags=["archive"])

STATUSES = ["open", "running", "answered", "failed", "refused"]


class ArchiveRequestOut(ArchiveRequest):
    finds: list[ArchiveFind] = []


class ArchiveRequestsOut(BaseModel):
    requests: list[ArchiveRequestOut]  # newest first


@router.get("/requests")
def requests(
    slug: Slug, keeper: Keeper, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> ArchiveRequestsOut:
    store = keeper.store_for(slug)
    rows = store.read("ledger/archive_requests", {"statuses": STATUSES, "limit": limit})
    found = [ArchiveRequest(**r) for r in rows]
    finds: dict[str, list[ArchiveFind]] = {r.uid: [] for r in found}
    if found:
        for row in store.read("ledger/archive_finds", {"requests": list(finds)}):
            find = ArchiveFind(**row)
            finds[find.request].append(find)
    return ArchiveRequestsOut(
        requests=[ArchiveRequestOut(**r.model_dump(), finds=finds[r.uid]) for r in found]
    )
