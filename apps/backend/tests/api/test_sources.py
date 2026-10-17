"""Sources routes: each configured source with its status, the graph's counts per source label,
leftover sync records and removing one, and a build that downloads only some sources."""

from __future__ import annotations

from pathlib import Path

import pytest
from backend import registry
from backend.api import create_app
from brain import db, loader
from brain.config import CompanyConfig
from brain.testing import needs_graph, synthetic_company
from fastapi.testclient import TestClient

from .conftest import write
from .test_builds import wait_done


@pytest.fixture
def no_graph_yet(monkeypatch):
    monkeypatch.setattr("backend.api.sources.db.graph_exists", lambda slug: False)


def test_sources_of_unknown_company_is_404(client, api_root):
    assert client.get("/api/companies/nope/sources").status_code == 404


def test_a_company_never_built_lists_its_config(client, api_root, no_graph_yet):
    """Rows come from the YAML and the adapters' checks, so they show before any build."""
    cfg = synthetic_company("acme_labs", folder=Path("data/inbox/acme_labs/records"))
    registry.write_new(cfg)
    body = client.get("/api/companies/acme_labs/sources").json()
    assert body["built"] is False and body["since"] == "2026-01-01"
    assert body["labels"] == [] and body["leftovers"] == []
    [row] = body["sources"]
    assert row["key"] == "canonical_jsonl:data/inbox/acme_labs/records"
    assert row["type"] == "canonical_jsonl" and row["location"] == "data/inbox/acme_labs/records"
    assert row["status"] == "skipped" and row["downloads"] is False
    assert row["problem"] == "Folder data/inbox/acme_labs/records does not exist"
    assert row["last_run"] is None and row["records"] is None


def test_a_folder_that_exists_is_never_synced_until_loaded(client, api_root, no_graph_yet):
    write(api_root, "acme_labs", name="Acme Labs")  # the real synthetic folder: it exists
    [row] = client.get("/api/companies/acme_labs/sources").json()["sources"]
    assert row["status"] == "never" and row["problem"] is None


def test_github_without_a_token_blocks_the_build(client, api_root, no_graph_yet, monkeypatch):
    base = synthetic_company("acme_labs").model_dump(mode="json")
    github = [{"type": "github", "repo": "acme/widgets", "include": ["issues"]}]
    registry.write_new(
        CompanyConfig.model_validate({**base, "data_permission": "public", "sources": github})
    )

    def no_token():
        from brain.adapters.github.client import GithubError

        raise GithubError("no token")

    monkeypatch.setattr("brain.adapters.github.client.token", no_token)
    [row] = client.get("/api/companies/acme_labs/sources").json()["sources"]
    assert row["status"] == "blocked" and row["downloads"] is True
    assert row["location"] == "acme/widgets" and row["reads"] == ["issues"]
    assert "GITHUB_TOKEN" in row["problem"]


def test_a_build_can_download_only_named_sources(client, api_root, runner, gate):
    write(api_root, "acme_labs", name="Acme Labs")
    key = client.get("/api/companies/acme_labs/sources").json()["sources"][0]["key"]
    started = client.post("/api/companies/acme_labs/builds", json={"sources": [key]})
    assert started.status_code == 202
    gate.set()
    wait_done(runner, "acme_labs")
    assert f"fetch({[key]})" in runner.steps.calls and "ingest(full=False)" in runner.steps.calls


def test_a_build_refuses_a_source_the_company_lacks(client, api_root):
    write(api_root, "acme_labs", name="Acme Labs")
    for sources in (["github:nope/nope"], []):
        answer = client.post("/api/companies/acme_labs/builds", json={"sources": sources})
        assert answer.status_code == 422


def test_a_configured_source_is_not_a_leftover(client, api_root):
    write(api_root, "acme_labs", name="Acme Labs")
    key = client.get("/api/companies/acme_labs/sources").json()["sources"][0]["key"]
    answer = client.delete("/api/companies/acme_labs/sources/leftovers", params={"key": key})
    assert answer.status_code == 409 and "still a source" in answer.json()["detail"]


def test_no_leftover_is_removed_while_a_build_runs(client, api_root, monkeypatch):
    write(api_root, "acme_labs", name="Acme Labs")
    monkeypatch.setattr("backend.api.sources.db.graph_exists", lambda slug: True)
    monkeypatch.setattr(
        "backend.api.sources.db.run", lambda *a, **k: pytest.fail("must not delete")
    )
    assert client.post("/api/companies/acme_labs/builds").status_code == 202  # held at the gate
    answer = client.delete(
        "/api/companies/acme_labs/sources/leftovers", params={"key": "canonical_jsonl:old"}
    )
    assert answer.status_code == 409 and "running" in answer.json()["detail"]


def test_an_unknown_leftover_is_404(client, api_root, no_graph_yet):
    write(api_root, "acme_labs", name="Acme Labs")
    answer = client.delete(
        "/api/companies/acme_labs/sources/leftovers", params={"key": "canonical_jsonl:old"}
    )
    assert answer.status_code == 404


@needs_graph
def test_counts_sync_records_and_leftovers(api_root, runner, synthetic_graph):
    write(api_root, synthetic_graph, name=synthetic_graph)
    client = TestClient(create_app(runner))
    # The shared test graph is loaded without SyncStates: add one for the configured source and
    # one for a folder no longer configured, and take both away again.
    key = client.get(f"/api/companies/{synthetic_graph}/sources").json()["sources"][0]["key"]
    old = "canonical_jsonl:apps/backend/examples/synthetic_company"
    loader.set_sync_state(synthetic_graph, "canonical_jsonl", key, None, "2025-06-01", 30)
    loader.set_sync_state(synthetic_graph, "canonical_jsonl", old, None, "2026-01-01", 7)
    try:
        body = client.get(f"/api/companies/{synthetic_graph}/sources").json()
        gone = client.delete(
            f"/api/companies/{synthetic_graph}/sources/leftovers", params={"key": old}
        )
        after = client.get(f"/api/companies/{synthetic_graph}/sources").json()
    finally:
        for k in (key, old):
            db.run(synthetic_graph, "load/sync_state_forget", {"key": k})

    assert body["built"] is True
    [row] = body["sources"]
    assert row["status"] == "synced" and row["records"] == 30 and row["last_run"]
    assert row["window_changed"] is True  # stored for 2025-06-01, the YAML says 2026-01-01
    labels = {g["source"]: g for g in body["labels"]}
    assert {"canonical_jsonl", "derived"} <= labels.keys()
    jsonl = labels["canonical_jsonl"]
    assert jsonl["total"] == sum(k["count"] for k in jsonl["kinds"])
    work = [k for k in jsonl["kinds"] if k["label"] == "WorkItem"]
    assert work and all(sum(k["states"].values()) == k["count"] for k in work)
    assert [left["key"] for left in body["leftovers"]] == [old]
    assert body["leftovers"][0]["records"] == 7

    assert gone.status_code == 204
    assert after["leftovers"] == [] and after["labels"] == body["labels"]  # nodes stay
