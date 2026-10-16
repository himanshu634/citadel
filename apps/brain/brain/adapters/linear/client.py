"""Minimal Linear GraphQL client: auth, rate limits, retries.

Why: every Linear call in the adapter goes through `LinearClient.query`, so key handling and
rate-limit waits live in one place. Linear answers a rate-limited call with HTTP 400 and an
`extensions.code` of `RATELIMITED`, and reports the budget in `X-RateLimit-Requests-*` headers
(reset time in UTC epoch milliseconds). We sleep until the reset instead of failing halfway
through a fetch, and also when a successful call leaves the budget low.
"""

from __future__ import annotations

import time
from functools import cache
from pathlib import Path
from typing import Any

import httpx

from brain.config import get_settings

API = "https://api.linear.app/graphql"
QUERIES_DIR = Path(__file__).parent / "queries"
LOW_REQUESTS = 50  # requests left before we wait for the reset
RESET_MARGIN = 1  # seconds added to every wait for the reset


class LinearError(RuntimeError):
    pass


class LinearRateLimited(LinearError):
    """Linear kept answering with a rate-limit error."""


def token() -> str:
    """LINEAR_API_KEY from env/.env (a personal API key)."""
    if key := get_settings().linear_api_key:
        return key
    raise LinearError("no Linear API key: set LINEAR_API_KEY in .env")


@cache
def graphql(name: str) -> str:
    """Load a GraphQL document from adapters/linear/queries/<name>.graphql."""
    return (QUERIES_DIR / f"{name}.graphql").read_text()


def _json(resp: httpx.Response) -> dict[str, Any]:
    try:
        payload = resp.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _is_rate_limited(resp: httpx.Response, payload: dict[str, Any]) -> bool:
    if resp.status_code == 429:
        return True
    errors = payload.get("errors") or []
    return any((e.get("extensions") or {}).get("code") == "RATELIMITED" for e in errors)


def _seconds_until_reset(resp: httpx.Response) -> float | None:
    """Seconds until the budget resets, from the reset header; None when it is missing."""
    raw = resp.headers.get("X-RateLimit-Requests-Reset")
    if raw is None:
        return None
    try:
        return max(0.0, int(raw) / 1000 - time.time()) + RESET_MARGIN
    except ValueError:
        return None


class LinearClient:
    """`attempts` bounds retries of rate limits and 5xx answers; a quick check can pass
    attempts=1 and never sleeps. `transport` swaps the HTTP transport (tests). Close it (or use
    it in a `with`) when done."""

    def __init__(
        self,
        log=print,
        *,
        timeout: float = 60,
        attempts: int = 5,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        # Linear takes a personal API key as-is; a "Bearer" prefix is only for OAuth tokens.
        self._http = httpx.Client(
            timeout=timeout,
            transport=transport,
            headers={"Authorization": token(), "User-Agent": "company-brain"},
        )
        self._log = log
        self._attempts = attempts

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> LinearClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def query(self, name: str, variables: dict[str, Any], document: str | None = None) -> dict:
        """Run a named GraphQL query, retrying transient errors and waiting out rate limits.

        `document` overrides the file text.
        """
        body = {"query": document or graphql(name), "variables": variables}
        rate_limited = False
        for attempt in range(self._attempts):
            resp = self._http.post(API, json=body)
            payload = _json(resp)
            rate_limited = _is_rate_limited(resp, payload)
            if rate_limited or resp.status_code in (502, 503, 504):
                if attempt + 1 == self._attempts:
                    break  # nothing left to retry, so do not sleep for nothing
                wait = _seconds_until_reset(resp) if rate_limited else None
                if wait is None:
                    wait = 2**attempt * 5
                what = "rate limited" if rate_limited else str(resp.status_code)
                self._log(f"  linear {what}; retrying in {wait:.0f}s")
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                raise LinearError(f"Linear API {resp.status_code}: {resp.text[:300]}")
            if payload.get("errors"):
                raise LinearError(f"GraphQL errors in {name}: {payload['errors'][:2]}")
            if payload.get("data") is None:
                raise LinearError(f"Linear returned no data for {name}")
            self._respect_rate_limit(resp)
            return payload["data"]
        error = LinearRateLimited if rate_limited else LinearError
        raise error(f"Linear API kept failing for {name}")

    def _respect_rate_limit(self, resp: httpx.Response) -> None:
        remaining = resp.headers.get("X-RateLimit-Requests-Remaining")
        if remaining is None or not remaining.isdigit() or int(remaining) >= LOW_REQUESTS:
            return
        wait = _seconds_until_reset(resp)
        if wait is None:
            return
        self._log(f"  linear rate limit low ({remaining} left); sleeping {wait:.0f}s")
        time.sleep(wait)
