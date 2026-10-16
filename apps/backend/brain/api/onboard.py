"""Add a company from one public GitHub repository: the lookup the dialog shows while you type,
and the create that writes the company and starts its first build in one request.

Why: the dialog asks for a repository and nothing else (`brain.onboard` derives the rest).
Visibility is checked again on create, because the dialog's lookup is only advice: a private
repository is refused here (422 `private_repo`) instead of minutes later by the fetch. The file
is written and the build started under the same lock as the Settings save. A company whose
build did not start is kept and said so (201 with `build_error`), as the step-by-step form does.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException

from brain import onboard, registry
from brain.api import checks
from brain.api.companies import Runner, StartLock, _detail, _field_errors, slug_taken
from brain.api.models import CompanyRef, OnboardIn, OnboardOut, RepoLookup
from brain.config import CompanyConfig

log = logging.getLogger(__name__)

router = APIRouter(prefix="/onboard", tags=["onboard"])

PRIVATE = "Citadel reads public repositories only"


def _ref(cfg: CompanyConfig | None) -> CompanyRef | None:
    return CompanyRef(slug=cfg.slug, name=cfg.name) if cfg is not None else None


def _found(owner: str, name: str) -> tuple[str, bool, str] | None:
    """(owner/name as GitHub spells it, private, owner display name), or None if not found."""
    repo = checks.ask_repo("repo_owner", owner, name)
    if repo is None:
        return None
    login = repo["owner"]["login"]
    return (
        repo["nameWithOwner"],
        repo["isPrivate"],
        onboard.display_name(login, repo["owner"].get("name")),
    )


@router.get("/github/{owner}/{name}")
def lookup(
    owner: Annotated[str, checks.OWNER], name: Annotated[str, checks.NAME], runner: Runner
) -> RepoLookup:
    found = _found(owner, name)
    if found is None:
        return RepoLookup(repo=f"{owner}/{name}", exists=False)
    repo, private, owner_name = found
    if private:
        return RepoLookup(repo=repo, exists=True, private=True, owner_name=owner_name)
    slug = onboard.first_free(onboard.candidates(repo), lambda s: slug_taken(runner, s) is not None)
    return RepoLookup(
        repo=repo,
        exists=True,
        private=False,
        owner_name=owner_name,
        name=onboard.company_name(repo, owner_name, slug),
        slug=slug,
        since=onboard.since(onboard.today()).isoformat(),
        company=_ref(onboard.company_reading(repo)),
        owner_company=_ref(onboard.company_of_owner(repo.split("/")[0])),
    )


@router.post("/github", status_code=201)
def create(body: OnboardIn, runner: Runner, lock: StartLock):
    owner, name = body.repo.split("/")
    found = _found(owner, name)
    if found is None:
        detail = {"code": "not_found", "message": f"GitHub has no public repository {body.repo}"}
        raise HTTPException(status_code=422, detail=detail)
    repo, private, owner_name = found
    if private:
        raise HTTPException(status_code=422, detail={"code": "private_repo", "message": PRIVATE})
    if (reader := onboard.company_reading(repo)) is not None:
        detail = {"code": "repo_taken", "slug": reader.slug, "name": reader.name}
        raise HTTPException(status_code=409, detail=detail)

    with lock:  # pick the slug, write and start as one step; other starts take the same lock
        slug = body.slug or onboard.first_free(
            onboard.candidates(repo), lambda s: slug_taken(runner, s) is not None
        )
        draft = onboard.draft(
            repo,
            body.name or onboard.company_name(repo, owner_name, slug),
            slug,
            onboard.today(),
        )
        cfg, errors = registry.validate_draft(draft)
        if cfg is None:
            return _field_errors(errors)
        if taken := slug_taken(runner, cfg.slug):
            raise HTTPException(status_code=409, detail={"code": "slug_taken", "message": taken})
        try:
            registry.write_new(cfg)
        except FileExistsError as exc:  # written outside the API since the check
            detail = {"code": "slug_taken", "message": f"{cfg.slug} is already a company"}
            raise HTTPException(status_code=409, detail=detail) from exc
        try:
            build, error = runner.start(cfg.slug, "build"), None
        except Exception as exc:  # the company stays; the dialog offers to try again
            log.exception("first build of %s did not start", cfg.slug)
            build, error = None, str(exc) or type(exc).__name__
    return OnboardOut(company=_detail(cfg, runner), build=build, build_error=error)
