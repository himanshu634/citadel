"""Overview and tool routes: what the company's overview page and agents read."""

from __future__ import annotations

import pytest
from backend.api import create_app
from backend.api.companies import status_of
from brain import db, schema, tools
from brain.testing import falkordb_up, needs_graph
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from .conftest import write


@pytest.fixture
def api_client_with(api_root, runner):
    """A client whose companies/ folder holds one YAML per given slug."""

    def make(*slugs: str) -> TestClient:
        for slug in slugs:
            write(api_root, slug, name=slug)
        return TestClient(create_app(runner))

    return make


def test_overview_of_unknown_company_is_404(client, api_root):
    assert client.get("/api/companies/nope/overview").status_code == 404


@needs_graph
def test_overview_is_scoped_to_its_company(api_client_with, synthetic_graph):
    empty = "test_empty"
    db.delete_graph(empty)
    schema.apply_schema(empty)
    try:
        client = api_client_with(synthetic_graph, empty)
        full = client.get(f"/api/companies/{synthetic_graph}/overview").json()
        none = client.get(f"/api/companies/{empty}/overview").json()
    finally:
        db.delete_graph(empty)
    assert full["recent"] and not none["recent"] and not none["people"]
    assert full["slug"] == synthetic_graph and none["slug"] == empty
    assert full["since"] == "2026-01-01" and full["name"] == synthetic_graph
    assert len(full["recent"]) == 10 and full["recent"][0]["uid"] == "synthetic:issue:14"
    assert full["recent"][0]["last_at"].startswith("2026-09-10")
    assert {"person_uid", "display_name"} <= full["people"][0].keys()
    assert len(full["systems"]) <= 8 and len(full["people"]) <= 8
    assert {c["type"] for c in full["counts"]} >= {"Person", "WorkItem", "System"}
    assert all(c["kind"] == "node" for c in full["counts"])
    assert none["counts"] == [] and none["systems"] == []


@needs_graph
def test_tool_list_and_call(api_client_with, synthetic_graph):
    client = api_client_with(synthetic_graph)
    listed = client.get(f"/api/companies/{synthetic_graph}/tools").json()
    assert listed["slug"] == synthetic_graph
    assert {t["name"] for t in listed["tools"]} == set(tools.TOOLS) - {"run_cypher"}
    recent = next(t for t in listed["tools"] if t["name"] == "recent_work_items")
    assert recent["description"] and recent["params_schema"]["properties"]["limit"]

    response = client.post(
        f"/api/companies/{synthetic_graph}/tools/recent_work_items", json={"limit": 2}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == synthetic_graph and body["tool"] == "recent_work_items"
    assert [r["uid"] for r in body["rows"]] == ["synthetic:issue:14", body["rows"][1]["uid"]]
    assert len(body["rows"]) == 2


@needs_graph
def test_tool_call_without_body_uses_defaults(api_client_with, synthetic_graph):
    client = api_client_with(synthetic_graph)
    response = client.post(f"/api/companies/{synthetic_graph}/tools/graph_stats")
    assert response.status_code == 200 and response.json()["rows"]


@pytest.mark.parametrize("body", [{"slug": "other"}, {"name": "x"}, {"limit": 2, "tool": "y"}])
def test_tool_params_outside_the_model_are_ignored(api_client_with, monkeypatch, body):
    """Body keys that are not the tool's params never reach tools.call (no TypeError, and the
    slug and tool always come from the path)."""
    client = api_client_with("acme")
    ran: list[tuple] = []
    monkeypatch.setattr(db, "graph_exists", lambda slug: True)
    monkeypatch.setattr(db, "run", lambda slug, query, params, **k: ran.append((slug, query)) or [])
    r = client.post("/api/companies/acme/tools/recent_work_items", json=body)
    assert r.status_code == 200
    assert r.json() == {"slug": "acme", "tool": "recent_work_items", "rows": []}
    assert ran == [("acme", "tools/recent_work_items")]


def test_unknown_tool_is_404_and_bad_params_are_422(api_client_with, monkeypatch):
    client = api_client_with("acme")
    monkeypatch.setattr(db, "run", lambda *a, **k: [])
    assert client.post("/api/companies/acme/tools/drop_everything", json={}).status_code == 404
    assert client.post("/api/companies/nope/tools/graph_stats", json={}).status_code == 404
    bad = client.post("/api/companies/acme/tools/impact_of", json={})  # system is required
    assert bad.status_code == 422
    bad = client.post("/api/companies/acme/tools/recent_work_items", json={"limit": 0})
    assert bad.status_code == 422


def test_agent_only_tools_are_not_served(api_client_with, monkeypatch):
    """run_cypher runs a query the caller writes: Ask may use it, the HTTP API may not."""
    client = api_client_with("acme")
    ran: list[str] = []
    monkeypatch.setattr(db, "graph_exists", lambda slug: True)
    monkeypatch.setattr(db, "run_cypher", lambda slug, text, *a: ran.append(text) or ([], []))
    r = client.post(
        "/api/companies/acme/tools/run_cypher", json={"query": "MATCH (n) RETURN n LIMIT 1"}
    )
    assert r.status_code == 404 and ran == []
    assert tools.TOOLS["run_cypher"].agent_only


@pytest.mark.parametrize("error", [RedisConnectionError, RedisTimeoutError])
def test_overview_and_tools_are_503_when_the_graph_is_down(api_client_with, monkeypatch, error):
    client = api_client_with("acme")

    def down(slug):
        raise error("unreachable")

    monkeypatch.setattr(db, "graph_exists", down)
    for r in (
        client.get("/api/companies/acme/overview"),
        client.post("/api/companies/acme/tools/graph_stats", json={}),
    ):
        assert r.status_code == 503 and r.json() == {"detail": "FalkorDB is not reachable"}


def test_semantic_search_with_embeddings_off_is_503_with_the_sentence(
    api_client_with, monkeypatch, embeddings_off
):
    client = api_client_with("acme")
    monkeypatch.setattr(db, "graph_exists", lambda slug: True)
    r = client.post("/api/companies/acme/tools/semantic_search", json={"text": "invoice"})
    assert r.status_code == 503
    assert r.json() == {"detail": tools.SEMANTIC_OFF}


@pytest.fixture
def graph_deleted_after_the_check(monkeypatch):
    """graph_exists says yes once (the route's check), then the truth: a rebuild deleted it."""
    if falkordb_up():
        real, asked = db.graph_exists, []

    def racy(slug):
        asked.append(slug)
        return len(asked) == 1 or real(slug)

    monkeypatch.setattr(db, "graph_exists", racy)


@needs_graph
def test_overview_of_a_graph_deleted_mid_request_is_empty(
    api_client_with, graph_deleted_after_the_check
):
    body = api_client_with("test_gone").get("/api/companies/test_gone/overview").json()
    assert body["recent"] == [] and body["people"] == [] and body["counts"] == []


@needs_graph
def test_tool_call_on_a_graph_deleted_mid_request_is_empty(
    api_client_with, graph_deleted_after_the_check
):
    r = api_client_with("test_gone").post("/api/companies/test_gone/tools/recent_work_items")
    assert r.status_code == 200 and r.json()["rows"] == []


@needs_graph
def test_status_of_a_graph_deleted_mid_request_is_empty(graph_deleted_after_the_check):
    assert status_of("test_gone") == ("empty", None)
