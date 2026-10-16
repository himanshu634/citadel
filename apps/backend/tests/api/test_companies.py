"""Company reads: GET /api/companies and /api/companies/{slug}."""

from __future__ import annotations

import time

import pytest
from agents import checkpoint
from brain import config, db, loader
from brain.api import create_app
from brain.api.companies import status_of
from brain.jobs import JobRunner
from conftest import FakeSteps, needs_graph
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from .conftest import write

VALID_DRAFT = {
    "slug": "acme_labs",
    "name": "Acme Labs",
    "data_permission": "own",
    "window": {"since": "2026-04-15"},
    "sources": [{"type": "github", "repo": "acme/widgets"}],
}


def test_list_is_sorted_by_name_and_includes_invalid(client, api_root):
    write(api_root, "zeta", name="Zeta")
    write(api_root, "acme_labs", name="Acme Labs")
    (api_root / "companies" / "broken.yaml").write_text("slug: [\n")
    body = client.get("/api/companies").json()
    assert [c["slug"] for c in body] == ["acme_labs", "zeta", "broken"]
    assert body[2]["status"] == "invalid" and body[2]["error"]


@pytest.mark.parametrize("slug", ["Acme-Labs", "nope", "..", "a%2Fb"])
def test_unknown_or_bad_slug_is_404(client, api_root, slug):
    assert client.get(f"/api/companies/{slug}").status_code == 404


def test_unknown_slug_detail_names_the_slug(client, api_root):
    response = client.get("/api/companies/nope")
    assert response.json() == {"detail": "No company nope"}


def test_get_returns_config(client, api_root):
    write(api_root, "acme_labs", name="Acme Labs")
    body = client.get("/api/companies/acme_labs").json()
    assert body["config"]["slug"] == "acme_labs" and body["status"] in {"ready", "empty"}


def test_get_broken_company_is_422_with_the_reason(client, api_root):
    (api_root / "companies" / "broken.yaml").write_text("slug: [\n")
    response = client.get("/api/companies/broken")
    assert response.status_code == 422 and response.json()["detail"]


def test_cors_allows_only_the_dev_frontend(client, api_root):
    def preflight(origin):
        return client.options(
            "/api/companies",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        )

    assert preflight("http://localhost:5173").headers["access-control-allow-origin"] == (
        "http://localhost:5173"
    )
    assert "access-control-allow-origin" not in preflight("http://evil.example").headers


@needs_graph
def test_status_from_graph(api_root, synthetic_graph):
    write(api_root, synthetic_graph, name="Test")
    assert status_of("test_never_built") == ("empty", None)  # no graph at all
    assert status_of(synthetic_graph) == ("empty", None)  # loaded, but never ingested via sync

    slug = "test_api_status"
    try:
        loader.set_sync_state(slug, "github", "github:acme/widgets", None, "2026-01-01", 3)
        status, last_synced_at = status_of(slug)
        assert status == "ready" and last_synced_at
    finally:
        db.delete_graph(slug)


def test_validate_returns_yaml_and_writes_nothing(client, api_root):
    r = client.post("/api/companies/validate", json=VALID_DRAFT).json()
    assert r["ok"] and r["errors"] == [] and r["yaml"].startswith("slug: acme_labs")
    assert r["slug_taken"] is False
    assert not (api_root / "companies" / "acme_labs.yaml").exists()


def test_validate_reports_field_errors_without_yaml(client, api_root):
    bad = {**VALID_DRAFT, "sources": [{"type": "github", "repo": "x"}]}
    r = client.post("/api/companies/validate", json=bad).json()
    assert not r["ok"] and r["yaml"] is None
    assert r["errors"][0]["loc"] == ["sources", 0, "repo"]


def test_validate_reports_slug_taken(client, api_root):
    write(api_root, "acme_labs", name="Acme Labs")
    assert client.post("/api/companies/validate", json=VALID_DRAFT).json()["slug_taken"]


def test_validate_slug_taken_even_when_other_fields_are_wrong(client, api_root):
    write(api_root, "acme_labs", name="Acme Labs")
    r = client.post("/api/companies/validate", json={**VALID_DRAFT, "sources": "nope"}).json()
    assert not r["ok"] and r["slug_taken"]


@pytest.mark.parametrize("slug", ["Acme-Labs", "../x", 7, None])
def test_validate_bad_slug_is_not_taken(client, api_root, slug):
    r = client.post("/api/companies/validate", json={**VALID_DRAFT, "slug": slug}).json()
    assert not r["ok"] and r["slug_taken"] is False


def test_create_writes_file(client, api_root):
    r = client.post("/api/companies", json=VALID_DRAFT)
    assert r.status_code == 201
    assert r.json()["slug"] == "acme_labs" and r.json()["config"]["name"] == "Acme Labs"
    assert config.load_company("acme_labs").name == "Acme Labs"


def test_create_twice_is_409(client, api_root):
    client.post("/api/companies", json=VALID_DRAFT)
    r = client.post("/api/companies", json=VALID_DRAFT)
    assert r.status_code == 409 and "already a company" in r.json()["detail"]
    assert r.json()["detail"] == "acme_labs is already a company. Pick another name"


# --- a slug used before: its graphs or build history are still there --------------------------

REUSED = (
    "acme_labs was used before and its data is still there. Pick another name, or delete that "
    "data with make reset SLUG=acme_labs CONFIRM=1 (if you already ran it, restart the API)"
)


def leave_build_history(runner) -> None:
    runner.jobs_dir.mkdir(parents=True)
    (runner.jobs_dir / "acme_labs.json").write_text("{}")


def leave_graphs(monkeypatch, *names: str) -> None:
    monkeypatch.setattr(checkpoint, "company_graphs", lambda slug: list(names))


@pytest.mark.parametrize(
    "leftover",
    [
        lambda runner, mp: leave_build_history(runner),
        lambda runner, mp: leave_graphs(mp, "brain_acme_labs"),
        lambda runner, mp: leave_graphs(mp, "agent_acme_labs"),
    ],
    ids=["build_history", "brain_graph", "agent_graph"],
)
def test_reused_slug_is_taken_until_reset(client, runner, api_root, monkeypatch, leftover):
    leftover(runner, monkeypatch)
    v = client.post("/api/companies/validate", json=VALID_DRAFT).json()
    assert v["ok"] and v["slug_taken"] is True and v["slug_taken_detail"] == REUSED
    r = client.post("/api/companies", json=VALID_DRAFT)
    assert r.status_code == 409 and r.json() == {"detail": REUSED}
    assert not (api_root / "companies" / "acme_labs.yaml").exists()


def test_existing_company_is_taken_without_reset_advice(client, api_root):
    write(api_root, "acme_labs", name="Acme Labs")
    v = client.post("/api/companies/validate", json=VALID_DRAFT).json()
    assert v["slug_taken_detail"] == "acme_labs is already a company. Pick another name"


def test_free_slug_has_no_taken_detail(client, api_root):
    v = client.post("/api/companies/validate", json=VALID_DRAFT).json()
    assert v["slug_taken"] is False and v["slug_taken_detail"] is None


@pytest.mark.parametrize("error", [RedisConnectionError, RedisTimeoutError])
def test_slug_check_with_the_graph_down_uses_the_files(client, api_root, monkeypatch, error):
    def down(slug):
        raise error("unreachable")

    monkeypatch.setattr(checkpoint, "company_graphs", down)
    assert client.post("/api/companies/validate", json=VALID_DRAFT).json()["slug_taken"] is False
    assert client.post("/api/companies", json=VALID_DRAFT).status_code == 201


def test_create_invalid_is_422_with_field_paths(client, api_root):
    bad = {**VALID_DRAFT, "sources": [{"type": "github", "repo": "x"}]}
    r = client.post("/api/companies", json=bad)
    assert r.status_code == 422 and r.json()["detail"][0]["loc"] == ["sources", 0, "repo"]
    assert not (api_root / "companies" / "acme_labs.yaml").exists()


def test_create_non_object_body_is_422(client, api_root):
    assert client.post("/api/companies", json=["not", "an", "object"]).status_code == 422


# --- FalkorDB unreachable: status from the builds, else `unknown`; never 503 -----------------


@pytest.fixture(params=[RedisConnectionError, RedisTimeoutError])
def graph_down(request, monkeypatch):
    """FalkorDB refuses (ConnectionError) or never answers (TimeoutError). Returns the slugs whose
    graph was asked for."""
    asked: list[str] = []

    def down(slug):
        asked.append(slug)
        raise request.param("unreachable")

    monkeypatch.setattr("brain.api.companies.status_of", down)
    return asked


def test_reachable_graph_is_reported(client, api_root):
    write(api_root, "acme_labs", name="Acme Labs")
    body = client.get("/api/companies").json()[0]
    assert body["status"] == "empty" and body["graph_reachable"] is True


def test_list_when_the_graph_is_down_is_unknown_and_asks_once(client, api_root, graph_down):
    write(api_root, "acme_labs", name="Acme Labs")
    write(api_root, "zeta", name="Zeta")
    r = client.get("/api/companies")
    assert r.status_code == 200
    assert [(c["status"], c["graph_reachable"]) for c in r.json()] == [("unknown", False)] * 2
    assert graph_down == ["acme_labs"]  # one timeout per request, not one per company


def test_get_when_the_graph_is_down_is_unknown(client, api_root, graph_down):
    write(api_root, "acme_labs", name="Acme Labs")
    r = client.get("/api/companies/acme_labs")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "unknown" and body["graph_reachable"] is False
    assert body["last_synced_at"] is None and body["config"]["slug"] == "acme_labs"


def test_create_when_the_graph_is_down_is_unknown(client, api_root, graph_down):
    r = client.post("/api/companies", json=VALID_DRAFT)
    assert r.status_code == 201
    assert r.json()["status"] == "unknown" and r.json()["graph_reachable"] is False
    assert config.load_company("acme_labs").name == "Acme Labs"


def test_put_when_the_graph_is_down_saves_and_is_unknown(client, api_root, graph_down):
    write(api_root, "acme_labs", name="Acme Labs")
    cfg = client.get("/api/companies/acme_labs").json()["config"]
    r = client.put("/api/companies/acme_labs", json={**cfg, "name": "Acme"})
    assert r.status_code == 200 and r.json()["status"] == "unknown"
    assert config.load_company("acme_labs").name == "Acme"


def test_building_when_the_graph_is_down_is_building(client, api_root, graph_down):
    write(api_root, "acme_labs", name="Acme Labs")
    client.post("/api/companies/acme_labs/builds", json={})  # held at the gate
    body = client.get("/api/companies/acme_labs").json()
    assert body["status"] == "building" and body["graph_reachable"] is False


def test_failed_build_when_the_graph_is_down_is_failed(api_root, tmp_path, graph_down):
    write(api_root, "acme_labs", name="Acme Labs")
    runner = JobRunner(steps=FakeSteps(fail_on="ingest"), jobs_dir=tmp_path / "jobs")
    client = TestClient(create_app(runner))
    client.post("/api/companies/acme_labs/builds", json={})
    deadline = time.monotonic() + 5
    while runner.current("acme_labs").state != "failed" and time.monotonic() < deadline:
        time.sleep(0.01)
    body = client.get("/api/companies/acme_labs").json()
    assert body["status"] == "failed" and body["error"] == "boom"
    assert body["graph_reachable"] is False


def test_a_yaml_filename_that_is_not_a_slug_is_listed_as_invalid(client, api_root):
    write(api_root, "acme_labs", name="Acme Labs")
    (api_root / "companies" / "Acme-Labs.yaml").write_text("slug: acme\n")
    r = client.get("/api/companies")
    assert r.status_code == 200
    odd = next(c for c in r.json() if c["slug"] == "Acme-Labs")
    assert odd["status"] == "invalid" and odd["error"] and odd["build"] is None
    assert odd["last_synced_at"] is None
    assert [c["status"] for c in r.json() if c["slug"] == "acme_labs"] == ["empty"]


def test_invalid_company_reports_graph_reachable(client, api_root):
    (api_root / "companies" / "broken.yaml").write_text("slug: [\n")
    body = client.get("/api/companies").json()[0]
    assert body["status"] == "invalid" and body["graph_reachable"] is True
