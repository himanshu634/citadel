"""Company reads: GET /api/companies and /api/companies/{slug}."""

from __future__ import annotations

import pytest
from brain import db, loader
from brain.api.companies import status_of
from conftest import needs_graph

from .conftest import write


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
