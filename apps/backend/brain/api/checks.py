"""GitHub checks for the onboarding form: is a token available, and is a repo public.

Why: the form asks these when a GitHub source card appears, so the user learns about a missing
token or a private repo (which needs `data_permission: own`) before saving. Only the token's
source is ever reported; its value is never returned, logged or put in an error message.
"""

from __future__ import annotations

import subprocess
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, HTTPException, Path

from brain.adapters.github.client import GithubClient, GithubError
from brain.config import get_settings

router = APIRouter(prefix="/checks", tags=["checks"])

NO_TOKEN = "No GitHub token: set GITHUB_TOKEN in .env or run gh auth login"


def token_source() -> Literal["env", "gh"] | None:
    """Where `client.token()` would find a token, without handing the token out."""
    if get_settings().github_token:
        return "env"
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return "gh" if out.stdout.strip() else None


def github_client() -> GithubClient:
    return GithubClient()


@router.get("/github")
def github_token() -> dict[str, str | None]:
    return {"token": token_source()}


@router.get("/github/{owner}/{name}")
def github_repo(
    owner: Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]*$")],
    name: Annotated[str, Path(pattern=r"^[A-Za-z0-9._-]+$")],
) -> dict[str, bool | None]:
    """Whether owner/name exists for our token, and if so whether it is private."""
    try:
        client = github_client()
    except GithubError as exc:  # the client only fails to build when there is no token
        raise HTTPException(status_code=503, detail=NO_TOKEN) from exc
    try:
        repo = client.query("repo_meta", {"owner": owner, "name": name})["repository"]
    except GithubError as exc:
        if "NOT_FOUND" in str(exc):  # GitHub answers a missing repo with a GraphQL error
            return {"exists": False, "private": None}
        raise HTTPException(status_code=502, detail="GitHub request failed") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="GitHub is not reachable") from exc
    if repo is None:
        return {"exists": False, "private": None}
    return {"exists": True, "private": repo["isPrivate"]}
