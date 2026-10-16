"""GitHub checks: is a token available, and does a repo exist / is it private. No network."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import httpx
import pytest
from brain.adapters.github import client as gh
from brain.adapters.github.client import GithubError, GithubRateLimited
from brain.api import checks


def test_token_check_without_token(client, monkeypatch):
    monkeypatch.setattr(checks, "token_source", lambda: None)
    assert client.get("/api/checks/github").json() == {"token": None}


@pytest.mark.parametrize("source", ["env", "gh"])
def test_token_check_reports_the_source_only(client, monkeypatch, source):
    monkeypatch.setattr(checks, "token_source", lambda: source)
    assert client.get("/api/checks/github").json() == {"token": source}


def _no_gh(*args, **kwargs):
    raise AssertionError("gh must not run when GITHUB_TOKEN is set")


def test_token_source_env_does_not_call_gh(monkeypatch):
    monkeypatch.setattr(checks, "get_settings", lambda: SimpleNamespace(github_token="t0k"))
    monkeypatch.setattr(subprocess, "run", _no_gh)
    assert checks.token_source() == "env"


def test_token_source_gh(monkeypatch):
    monkeypatch.setattr(checks, "get_settings", lambda: SimpleNamespace(github_token=None))
    done = subprocess.CompletedProcess([], 0, stdout="ghp_secret\n")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: done)
    assert checks.token_source() == "gh"


def test_token_source_none_when_gh_missing_or_logged_out(monkeypatch):
    monkeypatch.setattr(checks, "get_settings", lambda: SimpleNamespace(github_token=None))

    def missing(*a, **k):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(subprocess, "run", missing)
    assert checks.token_source() is None

    def logged_out(*a, **k):
        raise subprocess.CalledProcessError(1, "gh")

    monkeypatch.setattr(subprocess, "run", logged_out)
    assert checks.token_source() is None
    done = subprocess.CompletedProcess([], 0, stdout="\n")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: done)
    assert checks.token_source() is None


def test_token_source_gives_gh_five_seconds(monkeypatch):
    monkeypatch.setattr(checks, "get_settings", lambda: SimpleNamespace(github_token=None))
    seen: dict = {}

    def hangs(*args, **kwargs):
        seen.update(kwargs)
        raise subprocess.TimeoutExpired("gh", kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", hangs)
    assert checks.token_source() is None and seen["timeout"] == 5


def test_check_client_makes_one_short_attempt(monkeypatch):
    monkeypatch.setattr(gh, "token", lambda: "t0k")
    with checks.github_client() as c:
        assert c._http.timeout.read <= 10 and c._attempts == 1
        assert c._wait_for_rate_limit is False


class FakeClient:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls, self.closed = result, error, [], False

    def query(self, name, variables, document=None):
        self.calls.append((name, variables))
        if self.error:
            raise self.error
        return self.result

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def use(monkeypatch, fake):
    monkeypatch.setattr(checks, "github_client", lambda: fake)
    return fake


def test_repo_public(client, monkeypatch):
    fake = use(monkeypatch, FakeClient({"repository": {"isPrivate": False}}))
    r = client.get("/api/checks/github/acme/widgets")
    assert r.json() == {"exists": True, "private": False}
    assert fake.calls == [("repo_meta", {"owner": "acme", "name": "widgets"})]
    assert fake.closed


def test_repo_private(client, monkeypatch):
    use(monkeypatch, FakeClient({"repository": {"isPrivate": True}}))
    assert client.get("/api/checks/github/acme/widgets").json() == {"exists": True, "private": True}


def test_repo_null_is_not_found(client, monkeypatch):
    use(monkeypatch, FakeClient({"repository": None}))
    assert client.get("/api/checks/github/acme/nope").json() == {"exists": False, "private": None}


def test_repo_graphql_not_found_error_is_not_found(client, monkeypatch):
    err = GithubError("GraphQL errors in repo_meta: [{'type': 'NOT_FOUND'}]")
    fake = use(monkeypatch, FakeClient(error=err))
    assert client.get("/api/checks/github/acme/nope").json() == {"exists": False, "private": None}
    assert fake.closed


def test_repo_other_github_error_is_502(client, monkeypatch):
    fake = use(monkeypatch, FakeClient(error=GithubError("GitHub API 401: Bad credentials")))
    r = client.get("/api/checks/github/acme/widgets")
    assert r.status_code == 502 and "GitHub" in r.json()["detail"]
    assert fake.closed


def test_repo_unreachable_is_502(client, monkeypatch):
    fake = use(monkeypatch, FakeClient(error=httpx.ConnectTimeout("slow")))
    r = client.get("/api/checks/github/acme/widgets")
    assert r.status_code == 502 and r.json() == {"detail": "GitHub is not reachable"}
    assert fake.closed


def test_repo_rate_limited_is_429(client, monkeypatch):
    fake = use(monkeypatch, FakeClient(error=GithubRateLimited("rate limit")))
    r = client.get("/api/checks/github/acme/widgets")
    assert r.status_code == 429 and "rate limit" in r.json()["detail"]
    assert fake.closed


def test_repo_without_token_is_424(client, monkeypatch):
    def no_token():
        raise GithubError("no GitHub token: set GITHUB_TOKEN in .env or run `gh auth login`")

    monkeypatch.setattr(checks, "github_client", no_token)
    r = client.get("/api/checks/github/acme/widgets")
    assert r.status_code == 424
    assert r.json() == {"detail": "No GitHub token: set GITHUB_TOKEN in .env or run gh auth login"}


def test_repo_rejects_odd_owner_or_name(client, monkeypatch):
    use(monkeypatch, FakeClient({"repository": {"isPrivate": False}}))
    assert client.get("/api/checks/github/ac me/widgets").status_code == 422
