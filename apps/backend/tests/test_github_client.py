"""GithubClient: retries and rate-limit waits for fetches, one bounded attempt for checks."""

from __future__ import annotations

import subprocess

import httpx
import pytest
from brain.adapters.github import client as gh
from brain.adapters.github.client import GithubClient, GithubError, GithubRateLimited

OK = {"data": {"repository": {"isPrivate": False}, "rateLimit": {"remaining": 5000}}}
LOW = {"data": {"rateLimit": {"remaining": 1, "resetAt": "2099-01-01T00:00:00Z"}}}


@pytest.fixture
def slept(monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr(gh.time, "sleep", waits.append)
    monkeypatch.setattr(gh, "token", lambda: "t0k")
    return waits


def make(responses: list[httpx.Response], **kwargs) -> GithubClient:
    c = GithubClient(log=lambda msg: None, **kwargs)
    queue = iter(responses)
    c._http = httpx.Client(transport=httpx.MockTransport(lambda request: next(queue)))
    return c


def rate_limited() -> httpx.Response:
    return httpx.Response(403, text="API rate limit exceeded", headers={"retry-after": "60"})


def test_fetch_client_retries_and_waits(slept):
    c = make([httpx.Response(502), httpx.Response(200, json=OK)])
    assert c.query("repo_meta", {})["repository"] == {"isPrivate": False}
    assert slept == [5]


def test_fetch_client_gives_up_after_five_attempts_as_before(slept):
    c = make([httpx.Response(502)] * 5)
    with pytest.raises(GithubError, match="kept failing") as exc:
        c.query("repo_meta", {})
    assert not isinstance(exc.value, GithubRateLimited)
    assert slept == [5, 10, 20, 40, 80]


def test_fetch_client_rate_limited_to_the_end_keeps_its_message(slept):
    c = make([rate_limited()] * 5)
    with pytest.raises(GithubRateLimited, match="kept failing"):
        c.query("repo_meta", {})
    assert slept == [60] * 5


def test_fetch_client_waits_out_a_low_budget(slept):
    make([httpx.Response(200, json=LOW)]).query("repo_meta", {})
    assert len(slept) == 1 and slept[0] > 0


def test_single_attempt_rate_limit_raises_without_sleeping(slept):
    c = make([rate_limited()], attempts=1, wait_for_rate_limit=False)
    with pytest.raises(GithubRateLimited):
        c.query("repo_meta", {})
    assert slept == []


def test_single_attempt_server_error_raises_without_sleeping(slept):
    c = make([httpx.Response(503)], attempts=1, wait_for_rate_limit=False)
    with pytest.raises(GithubError) as exc:
        c.query("repo_meta", {})
    assert not isinstance(exc.value, GithubRateLimited) and slept == []


def test_no_rate_limit_wait_when_disabled(slept):
    make([httpx.Response(200, json=LOW)], wait_for_rate_limit=False).query("repo_meta", {})
    assert slept == []


def test_timeout_is_passed_to_the_http_client(slept):
    with GithubClient(log=print, timeout=7) as c:
        assert c._http.timeout.read == 7
    assert c._http.is_closed


def test_close(slept):
    c = make([])
    c.close()
    assert c._http.is_closed


def test_token_asks_gh_with_a_timeout(monkeypatch):
    monkeypatch.setattr(gh, "get_settings", lambda: type("S", (), {"github_token": None})())
    seen: dict = {}

    def hangs(*args, **kwargs):
        seen.update(kwargs)
        raise subprocess.TimeoutExpired("gh", kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", hangs)
    with pytest.raises(GithubError, match="no GitHub token"):
        gh.token()
    assert seen["timeout"] == 5
