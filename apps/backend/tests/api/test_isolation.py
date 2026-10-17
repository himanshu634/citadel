"""Isolation (spec 6.5, 8): two companies loaded side by side; every company route answers with
its own slug and only its own uids, and asking one company for the other's uid finds nothing."""

from __future__ import annotations

import time
from typing import Any

import pytest
from backend import registry
from backend.api import create_app
from backend.api.companies import status_of
from backend.testing import second_company
from brain import db, embeddings, tools
from brain.testing import FakeEmbedder, load_company, needs_graph, synthetic_company
from fastapi.testclient import TestClient

pytestmark = needs_graph

# Per company: arguments for the tools that need some, naming that company's own data.
ARGS = {
    "synthetic": {
        "system": "Auth",
        "login": "alice",
        "uid": "synthetic:pr:1",
        "text": "sessions",
        "from_uid": "person:alice",
        "to_uid": "system:Auth",
    },
    "second": {
        "system": "Engine",
        "login": "mira",
        "uid": "second:pr:1",
        "text": "engine",
        "from_uid": "person:mira",
        "to_uid": "system:Engine",
    },
}


def uids(value: Any) -> set[str]:
    """Every string under a key ending in 'uid', anywhere in a response body."""
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith("uid") and isinstance(item, str):
                found.add(item)
            else:
                found |= uids(item)
    elif isinstance(value, list):
        for item in value:
            found |= uids(item)
    return found


def tool_body(name: str, args: dict[str, str]) -> dict[str, str]:
    fields = tools.TOOLS[name].params.model_fields
    return {k: v for k, v in args.items() if k in fields}


def wait_done(runner, slug: str) -> None:
    deadline = time.monotonic() + 5
    while runner.current(slug).state not in ("done", "failed", "stopped"):
        assert time.monotonic() < deadline, f"build of {slug} did not finish"
        time.sleep(0.01)


def responses(client: TestClient, slug: str, args: dict[str, str]) -> dict[str, Any]:
    """Every company route of one company: name -> response."""
    base = f"/api/companies/{slug}"
    detail = client.get(base)
    out = {
        "get": detail,
        "overview": client.get(f"{base}/overview"),
        "tools": client.get(f"{base}/tools"),
        "builds/current": client.get(f"{base}/builds/current"),
        "put?dry_run": client.put(
            f"{base}?dry_run=1", json={**detail.json()["config"], "name": "Renamed"}
        ),
    }
    for name in tools.TOOLS:
        out[f"tools/{name}"] = client.post(f"{base}/tools/{name}", json=tool_body(name, args))
    return out


@pytest.fixture
def fake_embedder():
    """A FakeEmbedder for this test only, so semantic_search embeds questions like the chunks."""
    embeddings.set_embedder(FakeEmbedder())
    yield
    embeddings.set_embedder(None)


@pytest.fixture
def own_graphs():
    """Both companies in graphs of this test's own, deleted afterwards. The test embeds them:
    the session graphs (synthetic_graph, second_graph) must stay unembedded for later tests."""
    slugs = {"synthetic": "test_iso_synthetic", "second": "test_iso_second"}
    for slug in slugs.values():
        db.delete_graph(slug)
    load_company(synthetic_company(slugs["synthetic"]))
    load_company(second_company(slugs["second"]))
    yield slugs
    for slug in slugs.values():
        db.delete_graph(slug)


def test_every_company_route_answers_only_for_its_company(
    api_root, runner, gate, monkeypatch, own_graphs, fake_embedder
):
    monkeypatch.setattr("backend.api.companies.status_of", status_of)  # the real graph status
    registry.write_new(synthetic_company(own_graphs["synthetic"]))
    registry.write_new(second_company(own_graphs["second"]))
    client = TestClient(create_app(runner))
    gate.set()
    slugs = own_graphs
    for slug in slugs.values():
        client.post(f"/api/companies/{slug}/builds", json={})
        wait_done(runner, slug)
        # The test runner's build steps are fakes, so embed here: semantic_search must return
        # rows, or a leak of the other company's chunks could not show.
        report = embeddings.embed_pending(slug)
        assert report.skipped_reason is None, report

    seen: dict[str, set[str]] = {}
    for key, slug in slugs.items():
        seen[key] = set()
        for route, r in responses(client, slug, ARGS[key]).items():
            assert r.status_code == 200, (slug, route, r.text)
            body = r.json()
            assert body["slug"] == slug, (slug, route)
            if route == "tools/semantic_search":
                assert body["rows"], slug
            seen[key] |= uids(body)
        assert seen[key], slug

    assert {"synthetic:pr:1", "person:alice", "system:Auth"} <= seen["synthetic"]
    assert {"second:pr:1", "person:mira", "system:Engine"} <= seen["second"]
    assert seen["synthetic"].isdisjoint(seen["second"])
    listed = {c["slug"] for c in client.get("/api/companies").json()}
    assert listed == set(slugs.values())


def test_one_company_cannot_open_the_other_companys_nodes(
    api_root, runner, synthetic_graph, second_graph
):
    registry.write_new(synthetic_company(synthetic_graph))
    registry.write_new(second_company(second_graph))
    client = TestClient(create_app(runner))
    for asked, other in ((synthetic_graph, "second"), (second_graph, "synthetic")):
        for name in ("get_entity", "person_profile", "work_history", "experts_for_system"):
            r = client.post(
                f"/api/companies/{asked}/tools/{name}", json=tool_body(name, ARGS[other])
            )
            assert r.status_code == 200 and r.json()["rows"] == [], (asked, name, r.json())
