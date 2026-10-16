"""GitHub checks for the onboarding form: is a token available, and is a repo public.

Why: the form asks these when a GitHub source card appears, so the user learns about a missing
token or a private repo (which needs `data_permission: own`) before saving. Only the token's
source is ever reported; its value is never returned, logged or put in an error message.
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, HTTPException, Path

from brain.adapters.github import client
from brain.adapters.github.client import GithubClient, GithubError, GithubRateLimited
from brain.config import get_settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/checks", tags=["checks"])

NO_TOKEN = "No GitHub token: set GITHUB_TOKEN in .env or run gh auth login"
CHECK_TIMEOUT = 10  # seconds; the form asks while the user types, so never wait long


def token_source() -> Literal["env", "gh"] | None:
    """Where `client.token()` would find a token, without handing the token out."""
    if get_settings().github_token:
        return "env"
    out = client.gh_auth_token()
    return "gh" if out is not None and out.stdout.strip() else None


def github_client() -> GithubClient:
    """One short attempt, no retries and no rate-limit sleep: a request thread is never held."""
    return GithubClient(log=log.info, timeout=CHECK_TIMEOUT, attempts=1, wait_for_rate_limit=False)


@router.get("/github")
def github_token() -> dict[str, str | None]:
    return {"token": token_source()}


@router.get("/github/{owner}/{name}")
def github_repo(
    owner: Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]*$")],
    name: Annotated[str, Path(pattern=r"^[A-Za-z0-9._-]+$")],
) -> dict[str, bool | None]:
    """Whether owner/name exists for our token, and if so whether it is private. 424 without a
    token (the check depends on one), 429 when GitHub rate-limits us, 502 when it fails."""
    try:
        github = github_client()
    except GithubError as exc:  # the client only fails to build when there is no token
        raise HTTPException(status_code=424, detail=NO_TOKEN) from exc
    with github:
        try:
            repo = github.query("repo_meta", {"owner": owner, "name": name})["repository"]
        except GithubRateLimited as exc:
            detail = "GitHub rate limit reached; try again later"
            raise HTTPException(status_code=429, detail=detail) from exc
        except GithubError as exc:
            if "NOT_FOUND" in str(exc):  # GitHub answers a missing repo with a GraphQL error
                return {"exists": False, "private": None}
            raise HTTPException(status_code=502, detail="GitHub request failed") from exc
        except httpx.HTTPError as exc:  # includes timeouts
            raise HTTPException(status_code=502, detail="GitHub is not reachable") from exc
    if repo is None:
        return {"exists": False, "private": None}
    return {"exists": True, "private": repo["isPrivate"]}
