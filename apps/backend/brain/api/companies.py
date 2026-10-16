"""Company routes: the list for the rail, one company, validate/create for the onboarding form,
and the Settings save.

Why: a broken YAML file must show up in the list (so the user can fix it) instead of hiding
the other companies, and status comes from the build jobs and the graph, not from a guess about
the files. A Settings save that changes what the graph holds needs the user's confirmation
(`?rebuild=1`), because the rebuild empties the graph first; it is refused while a build runs.
"""

from __future__ import annotations

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

router = APIRouter(prefix="/companies", tags=["companies"])


Runner = Annotated[JobRunner, Depends(get_runner)]
StartLock = Annotated[threading.Lock, Depends(start_lock)]


def status_of(slug: str) -> tuple[Status, str | None]:
    """The graph's part of the status, (status, last_synced_at): `ready` once any source was
    ingested, else `empty`. `company_status` puts the build jobs on top."""
    if not db.graph_exists(slug):
        return "empty", None
    row = db.run(slug, "load/sync_state_latest", read_only=True)[0]
    if not row["sources"]:
        return "empty", None
    return "ready", row["last_synced_at"]


class CompanyStatus(NamedTuple):
    status: Status
    last_synced_at: str | None
    error: str | None  # the last build's error, when it failed
    build: BuildSummary | None


def company_status(runner: JobRunner, slug: str, graph: bool = True) -> CompanyStatus:
    """A queued or running build -> `building`; a last build that failed -> `failed`; else the
    graph decides. `graph=False` skips FalkorDB (it is down) and reports `empty` instead."""
    snap = runner.current(slug)
    build = BuildSummary.of(snap) if snap is not None else None
    if snap is not None and snap.state in ACTIVE:
        return CompanyStatus("building", None, None, build)
    status, last_synced_at = status_of(slug) if graph else ("empty", None)
    if snap is not None and snap.state == "failed":
        return CompanyStatus("failed", last_synced_at, snap.error, build)
    return CompanyStatus(status, last_synced_at, None, build)


def _out(cfg: CompanyConfig, runner: JobRunner, graph: bool = True) -> CompanyOut:
    state = company_status(runner, cfg.slug, graph)
    return CompanyOut(
        slug=cfg.slug,
        name=cfg.name,
        data_permission=cfg.data_permission,
        status=state.status,
        last_synced_at=state.last_synced_at,
        error=state.error,
        build=state.build,
    )


def _detail(cfg: CompanyConfig, runner: JobRunner, graph: bool = True) -> CompanyDetail:
    return CompanyDetail(
        **_out(cfg, runner, graph).model_dump(), config=cfg.model_dump(mode="json")
    )


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
    return [
        CompanyOut(slug=c.slug, name=c.slug, data_permission=None, status="invalid", error=c.error)
        if isinstance(c, registry.InvalidCompany)
        else _out(c, runner)
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
def create_company(draft: Annotated[dict, Body()], runner: Runner):
    cfg, errors = registry.validate_draft(draft)
    if cfg is None:
        return _field_errors(errors)
    try:
        registry.write_new(cfg)
    except FileExistsError as exc:
        detail = f"{cfg.slug} is already a company. Pick another name"
        raise HTTPException(status_code=409, detail=detail) from exc
    try:
        return _detail(cfg, runner)
    except (RedisConnectionError, RedisTimeoutError):
        return _detail(cfg, runner, graph=False)  # the file is saved; onboarding needs no graph


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
