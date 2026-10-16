"""Company reads: GET /api/companies and /api/companies/{slug}."""

from __future__ import annotations

import pytest
from brain import config, db, loader
from brain.api.companies import status_of
from conftest import needs_graph

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


def test_create_invalid_is_422_with_field_paths(client, api_root):
    bad = {**VALID_DRAFT, "sources": [{"type": "github", "repo": "x"}]}
    r = client.post("/api/companies", json=bad)
    assert r.status_code == 422 and r.json()["detail"][0]["loc"] == ["sources", 0, "repo"]
    assert not (api_root / "companies" / "acme_labs.yaml").exists()


def test_create_non_object_body_is_422(client, api_root):
    assert client.post("/api/companies", json=["not", "an", "object"]).status_code == 422
