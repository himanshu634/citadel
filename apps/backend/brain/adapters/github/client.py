"""Minimal GitHub GraphQL client: auth, rate limits, retries.

Why: every GitHub call in the adapter goes through `GithubClient.query`, so token handling and
rate-limit waits live in one place. Each query asks for `rateLimit { remaining resetAt }`; when
the budget runs low we sleep until the reset instead of failing halfway through a fetch.
"""

from __future__ import annotations

import subprocess
import time
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

import httpx

from brain.config import get_settings

API = "https://api.github.com/graphql"
QUERIES_DIR = Path(__file__).parent / "queries"
LOW_BUDGET = 100  # points left before we wait for the reset


class GithubError(RuntimeError):
    pass


def token() -> str:
    """GITHUB_TOKEN from env/.env, else the GitHub CLI's token (`gh auth token`)."""
    if t := get_settings().github_token:
        return t
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        out = None
    if out and out.stdout.strip():
        return out.stdout.strip()
    raise GithubError("no GitHub token: set GITHUB_TOKEN in .env or run `gh auth login`")


@cache
def graphql(name: str) -> str:
    """Load a GraphQL document from adapters/github/queries/<name>.graphql."""
    return (QUERIES_DIR / f"{name}.graphql").read_text()


class GithubClient:
    def __init__(self, log=print) -> None:
        self._http = httpx.Client(
            timeout=60,
            headers={"Authorization": f"Bearer {token()}", "User-Agent": "company-brain"},
        )
        self._log = log

    def query(self, name: str, variables: dict[str, Any], document: str | None = None) -> dict:
        """Run a named GraphQL query, retrying transient errors and waiting out rate limits.

        `document` overrides the file text (used by the blobs query, whose fields are generated).
        """
        body = {"query": document or graphql(name), "variables": variables}
        for attempt in range(5):
            resp = self._http.post(API, json=body)
            if resp.status_code in (502, 503, 504) or (
                resp.status_code in (403, 429) and "rate limit" in resp.text.lower()
            ):
                wait = int(resp.headers.get("retry-after", 0)) or 2**attempt * 5
                self._log(f"  github {resp.status_code}; retrying in {wait}s")
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                raise GithubError(f"GitHub API {resp.status_code}: {resp.text[:300]}")
            payload = resp.json()
            if payload.get("errors"):
                raise GithubError(f"GraphQL errors in {name}: {payload['errors'][:2]}")
            data = payload["data"]
            self._respect_rate_limit(data.get("rateLimit"))
            return data
        raise GithubError(f"GitHub API kept failing for {name}")

    def _respect_rate_limit(self, rl: dict[str, Any] | None) -> None:
        if not rl or rl["remaining"] > LOW_BUDGET:
            return
        reset = datetime.fromisoformat(rl["resetAt"].replace("Z", "+00:00"))
        wait = max(0, (reset - datetime.now(UTC)).total_seconds()) + 5
        self._log(f"  github rate limit low ({rl['remaining']} left); sleeping {wait:.0f}s")
        time.sleep(wait)
