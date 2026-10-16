"""Company routes: the list for the rail, one company, validate/create for the onboarding form,
and the Settings save.

Why: a broken YAML file must show up in the list (so the user can fix it) instead of hiding
the other companies, and status comes from the build jobs and the graph, not from a guess about
the files. A Settings save that changes what the graph holds needs the user's confirmation
(`?rebuild=1`), because the rebuild empties the graph first; it is refused while a build runs.
"""

from __future__ import annotations

import logging
import threading
from typing import Annotated, NamedTuple

import yaml
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from brain import config_diff, db, registry
from brain.api.deps import company_slug, get_runner, start_lock
from brain.api.models import CompanyDetail, CompanyOut, Status, ValidateOut
from brain.config import CompanyConfig
from brain.config_diff import ConfigDiff
from brain.jobs import ACTIVE, BuildSnapshot, BuildSummary, JobRunner, JobRunning

log = logging.getLogger(__name__)

router = APIRouter(prefix="/companies", tags=["companies"])

GRAPH_DOWN = (RedisConnectionError, RedisTimeoutError)  # refused, or no answer to the connect


Runner = Annotated[JobRunner, Depends(get_runner)]
StartLock = Annotated[threading.Lock, Depends(start_lock)]


def status_of(slug: str) -> tuple[Status, str | None]:
    """The graph's part of the status, (status, last_synced_at): `ready` once any source was
    ingested, else `empty`. `company_status` puts the build jobs on top."""
    if not db.graph_exists(slug):
        return "empty", None
    rows = db.run(slug, "load/sync_state_latest", read_only=True)
    if not rows or not rows[0]["sources"]:  # no rows: a rebuild deleted the graph just now
        return "empty", None
    return "ready", rows[0]["last_synced_at"]


class CompanyStatus(NamedTuple):
    status: Status
    last_synced_at: str | None
    error: str | None  # the last build's error, when it failed
    build: BuildSummary | None
    graph_reachable: bool


def company_status(runner: JobRunner, slug: str, graph: bool = True) -> CompanyStatus:
    """A queued or running build -> `building`; a last build that failed -> `failed`; else the
    graph decides, or `unknown` when FalkorDB does not answer. The graph is asked in every case,
    so `last_synced_at` says whether a building company already has data. `graph=False` means
    the caller already found FalkorDB down in this request, so it is not asked again."""
    snap = runner.current(slug)
    build = BuildSummary.of(snap) if snap is not None else None
    status: Status = "unknown"
    last_synced_at: str | None = None
    reachable = False
    if graph:
        try:
            status, last_synced_at = status_of(slug)
            reachable = True
        except GRAPH_DOWN:
            log.warning("FalkorDB is not reachable; status of %s from its builds only", slug)
    if snap is not None and snap.state in ACTIVE:
        return CompanyStatus("building", last_synced_at, None, build, reachable)
    if snap is not None and snap.state == "failed":
        return CompanyStatus("failed", last_synced_at, snap.error, build, reachable)
    return CompanyStatus(status, last_synced_at, None, build, reachable)


def company_out(
    runner: JobRunner, company: CompanyConfig | registry.InvalidCompany, graph: bool = True
) -> CompanyOut:
    """A company as the list, the detail routes and the /api/events stream report it."""
    state = company_status(runner, company.slug, graph)
    common = {
        "slug": company.slug,
        "last_synced_at": state.last_synced_at,
        "build": state.build,
        "graph_reachable": state.graph_reachable,
    }
    if isinstance(company, registry.InvalidCompany):
        return CompanyOut(
            **common, name=company.slug, data_permission=None, status="invalid", error=company.error
        )
    return CompanyOut(
        **common,
        name=company.name,
        data_permission=company.data_permission,
        status=state.status,
        error=state.error,
    )


def _detail(cfg: CompanyConfig, runner: JobRunner) -> CompanyDetail:
    out = company_out(runner, cfg)
    return CompanyDetail(**out.model_dump(), config=cfg.model_dump(mode="json"))


def _field_errors(errors: list[registry.FieldError]) -> JSONResponse:
    """A plain JSONResponse, so the body is exactly {"detail": [FieldError, ...]}."""
    return JSONResponse(
        status_code=422, content={"detail": [e.model_dump(mode="json") for e in errors]}
    )


def read_config(slug: str) -> CompanyConfig:
    try:
        return registry.read(slug)
    except (ValueError, yaml.YAMLError) as exc:  # the file exists but does not validate
        raise HTTPException(status_code=422, detail=registry.describe(exc)) from exc


@router.get("")
def list_companies(runner: Runner) -> list[CompanyOut]:
    out: list[CompanyOut] = []
    graph = True  # after one company finds FalkorDB down, the rest do not wait for it again
    for company in registry.list_companies():
        out.append(company_out(runner, company, graph))
        graph = out[-1].graph_reachable
    return out


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
def create_company(draft: Annotated[dict, Body()], runner: Runner):
    cfg, errors = registry.validate_draft(draft)
    if cfg is None:
        return _field_errors(errors)
    try:
        registry.write_new(cfg)
    except FileExistsError as exc:
        detail = f"{cfg.slug} is already a company. Pick another name"
        raise HTTPException(status_code=409, detail=detail) from exc
    return _detail(cfg, runner)


@router.get("/{slug}")
def get_company(slug: Annotated[str, Depends(company_slug)], runner: Runner) -> CompanyDetail:
    return _detail(read_config(slug), runner)


@router.put(
    "/{slug}",
    response_model=CompanyDetail | ConfigDiff | BuildSnapshot,
    responses={202: {"model": BuildSnapshot}, 409: {}, 422: {}},
)
def save_company(
    slug: Annotated[str, Depends(company_slug)],
    draft: Annotated[dict, Body()],
    runner: Runner,
    lock: StartLock,
    dry_run: bool = False,
    rebuild: bool = False,
):
    """Settings save. `?dry_run=1` only reports what the change requires. A change that needs a
    rebuild is refused (409 `rebuild_required`) until it is sent with `?rebuild=1`, which saves
    and starts the rebuild (202, its snapshot); `?rebuild=1` without a change rebuilds as is
    (Retry rebuild). Other changes save, and new sources start a build that fetches only them."""
    cfg, errors = registry.validate_draft(draft)
    if cfg is None:
        return _field_errors(errors)
    if cfg.slug != slug:
        msg = f"must be {slug}: a company's slug cannot change"
        return _field_errors([registry.FieldError(loc=["slug"], msg=msg)])
    change = config_diff.diff(read_config(slug), cfg)
    if dry_run:
        return change
    if not change.changed and not rebuild:
        return _detail(cfg, runner)
    with lock:  # check, write and start as one step; POST /builds takes the same lock
        # Read again under the lock: a save that finished a moment ago changed the file.
        change = config_diff.diff(read_config(slug), cfg)
        snap = runner.current(slug)
        if snap is not None and snap.state in ACTIVE:
            raise HTTPException(status_code=409, detail=str(JobRunning(slug)))
        if change.rebuild and not rebuild:
            detail = {"rebuild_required": change.model_dump(mode="json")}
            return JSONResponse(status_code=409, content={"detail": detail})
        if change.changed:
            registry.update(slug, cfg)
        if rebuild:
            snap = runner.start(slug, "rebuild", refetch=set(change.refetch))
            return JSONResponse(status_code=202, content=snap.model_dump(mode="json"))
        if change.refetch:
            runner.start(slug, "build", refetch=set(change.refetch))
    return _detail(cfg, runner)
