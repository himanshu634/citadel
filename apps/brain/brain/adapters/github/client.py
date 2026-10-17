"""Minimal GitHub GraphQL client: auth, rate limits, retries.

Why: every GitHub call in the adapter goes through `GithubClient.query`, so token handling and
rate-limit waits live in one place. Each query asks for `rateLimit { remaining resetAt }`; when
the budget runs low we sleep until the reset instead of failing halfway through a fetch. The
API's onboarding check builds a client that makes one short attempt and never sleeps, so a
request thread is never held for minutes.
"""

from __future__ import annotations

import subprocess
import time
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

import httpx

from brain.adapters.runs import parse_ts
from brain.config import get_settings

API = "https://api.github.com/graphql"
QUERIES_DIR = Path(__file__).parent / "queries"
LOW_BUDGET = 100  # points left before we wait for the reset
GH_TIMEOUT = 5  # seconds for `gh auth token`, a local read that should answer at once


class GithubError(RuntimeError):
    pass


class GithubRateLimited(GithubError):
    """GitHub kept answering with a rate-limit error."""


def gh_auth_token() -> subprocess.CompletedProcess[str] | None:
    """`gh auth token`, or None when gh is missing, logged out or does not answer."""
    try:
        return subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=True, timeout=GH_TIMEOUT
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def token() -> str:
    """GITHUB_TOKEN from env/.env, else the GitHub CLI's token (`gh auth token`)."""
    if t := get_settings().github_token:
        return t
    out = gh_auth_token()
    if out and out.stdout.strip():
        return out.stdout.strip()
    raise GithubError("no GitHub token: set GITHUB_TOKEN in .env or run `gh auth login`")


@cache
def graphql(name: str) -> str:
    """Load a GraphQL document from adapters/github/queries/<name>.graphql."""
    return (QUERIES_DIR / f"{name}.graphql").read_text()


class GithubClient:
    """`attempts` and `wait_for_rate_limit` default to what a fetch needs (retry, then wait out
    the budget); a quick check passes attempts=1, wait_for_rate_limit=False and a short timeout.
    Close it (or use it in a `with`) when done."""

    def __init__(
        self,
        log=print,
        *,
        timeout: float = 60,
        attempts: int = 5,
        wait_for_rate_limit: bool = True,
    ) -> None:
        self._http = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Bearer {token()}", "User-Agent": "company-brain"},
        )
        self._log = log
        self._attempts = attempts
        self._wait_for_rate_limit = wait_for_rate_limit

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> GithubClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def query(self, name: str, variables: dict[str, Any], document: str | None = None) -> dict:
        """Run a named GraphQL query, retrying transient errors and waiting out rate limits.

        `document` overrides the file text (used by the blobs query, whose fields are generated).
        """
        body = {"query": document or graphql(name), "variables": variables}
        rate_limited = False
        for attempt in range(self._attempts):
            resp = self._http.post(API, json=body)
            rate_limited = resp.status_code in (403, 429) and "rate limit" in resp.text.lower()
            if resp.status_code in (502, 503, 504) or rate_limited:
                if self._attempts == 1:
                    break  # a single attempt (the API's check) never sleeps
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
            if self._wait_for_rate_limit:
                self._respect_rate_limit(data.get("rateLimit"))
            return data
        error = GithubRateLimited if rate_limited else GithubError
        raise error(f"GitHub API kept failing for {name}")

    def _respect_rate_limit(self, rl: dict[str, Any] | None) -> None:
        if not rl or rl["remaining"] > LOW_BUDGET:
            return
        reset = parse_ts(rl["resetAt"])
        wait = max(0, (reset - datetime.now(UTC)).total_seconds()) + 5
        self._log(f"  github rate limit low ({rl['remaining']} left); sleeping {wait:.0f}s")
        time.sleep(wait)
