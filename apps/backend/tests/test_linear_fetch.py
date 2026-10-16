"""Linear fetch: permission and workspace checks, teams snapshot, resumable issue runs."""

from __future__ import annotations

from typing import Any

import pytest
from brain.adapters.linear.client import LinearError
from brain.adapters.linear.fetch import check_permission, run
from brain.adapters.linear.source import LinearSource
from brain.adapters.runs import completed_pages, read_json
from brain.config import CompanyConfig

TEAMS = [
    {"id": "t1", "key": "IDN", "name": "Identity", "members": {"nodes": []}},
    {"id": "t2", "key": "PAY", "name": "Payments", "members": {"nodes": []}},
    {"id": "t3", "key": "OPS", "name": "Operations", "members": {"nodes": []}},
]
ISSUES = {"nodes": [{"id": "i1"}], "pageInfo": {"hasNextPage": False, "endCursor": "c1"}}


def company(permission: str = "own") -> CompanyConfig:
    return CompanyConfig.model_validate(
        {
            "slug": "lin_test",
            "name": "Linear test",
            "data_permission": permission,
            "window": {"since": "2026-01-01"},
            "sources": [],
        }
    )


def source(**kw: Any) -> LinearSource:
    return LinearSource.model_validate({"type": "linear", "workspace": "acme", **kw})


class FakeClient:
    """Answers by query name; records every call."""

    def __init__(self, teams: list[dict] | None = None, url_key: str = "acme") -> None:
        self.answers = {
            "meta": {"viewer": {"organization": {"urlKey": url_key, "name": "Acme"}}},
            "teams": {"teams": {"nodes": TEAMS if teams is None else teams}},
            "issues": {"issues": ISSUES},
        }
        self.calls: list[tuple[str, dict]] = []

    def query(self, name: str, variables: dict[str, Any]) -> dict:
        self.calls.append((name, dict(variables)))
        return self.answers[name]


def fetch(client: FakeClient, cache, src: LinearSource, comp: CompanyConfig | None = None):
    run(comp or company(), src, cache, client=client, log=lambda m: None)


def test_refuses_public_company(tmp_path):
    cache = tmp_path / "linear"
    client = FakeClient()

    with pytest.raises(PermissionError, match=r"companies/lin_test\.yaml"):
        fetch(client, cache, source(), company("public"))

    assert client.calls == []
    assert not cache.exists() or not list(cache.iterdir())


def test_check_permission_allows_own_and_synthetic():
    check_permission(company("own"))
    check_permission(company("synthetic"))


def test_refuses_other_workspace(tmp_path):
    cache = tmp_path / "linear"

    with pytest.raises(RuntimeError, match=r"acme.*synthetic-co|synthetic-co.*acme"):
        fetch(FakeClient(), cache, source(workspace="synthetic-co"))

    assert not list(cache.iterdir())


def test_unknown_team_key_refuses(tmp_path):
    cache = tmp_path / "linear"
    client = FakeClient(teams=[TEAMS[0]])

    with pytest.raises(LinearError, match="OPS"):
        fetch(client, cache, source(teams=["IDN", "OPS"]))

    assert "issues" not in [name for name, _ in client.calls]


def test_writes_meta_teams_and_issue_pages(tmp_path):
    cache = tmp_path / "linear"
    client = FakeClient()

    fetch(client, cache, source(teams=["IDN", "PAY"]))

    meta = read_json(cache / "meta.json")
    assert meta["urlKey"] == "acme"
    assert meta["name"] == "Acme"
    assert meta["fetched_at"]
    assert [t["key"] for t in read_json(cache / "teams.json")] == ["IDN", "PAY"]
    assert read_json(cache / "issues" / "state.json")["run"] is None
    assert [read_json(p) for p in completed_pages(cache / "issues")] == [ISSUES["nodes"]]
    (name, variables) = client.calls[-1]
    assert name == "issues"
    assert variables["teams"] == ["IDN", "PAY"]
    assert variables["first"] == 25


def test_empty_teams_means_every_team(tmp_path):
    cache = tmp_path / "linear"
    client = FakeClient()

    fetch(client, cache, source())

    assert [t["key"] for t in read_json(cache / "teams.json")] == ["IDN", "PAY", "OPS"]
    assert client.calls[-1][1]["teams"] == ["IDN", "PAY", "OPS"]
