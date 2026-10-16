"""Graph route: the whole company graph the Graph page draws."""

from __future__ import annotations

from backend.api import create_app
from brain.testing import needs_graph
from fastapi.testclient import TestClient

from .conftest import write


def test_graph_of_unknown_company_is_404(client):
    assert client.get("/api/companies/nope/graph").status_code == 404


def test_graph_never_built_is_empty(api_root, runner, monkeypatch):
    write(api_root, "fresh", name="Fresh")
    monkeypatch.setattr("brain.db.graph_exists", lambda slug: False)
    body = TestClient(create_app(runner)).get("/api/companies/fresh/graph").json()
    assert body["slug"] == "fresh"
    assert body["nodes"] == [] and body["edges"] == [] and body["territories"] == []


@needs_graph
def test_graph_draws_the_company(api_root, runner, synthetic_graph):
    write(api_root, synthetic_graph, name="Synthetic")
    client = TestClient(create_app(runner))
    body = client.get(f"/api/companies/{synthetic_graph}/graph").json()
    with_bots = client.get(f"/api/companies/{synthetic_graph}/graph?bots=true").json()

    labels = {n["label"] for n in body["nodes"]}
    assert labels <= {"Person", "Team", "System", "WorkItem", "Change", "Document"}
    assert "Chunk" not in labels and "SyncState" not in labels
    uids = {n["uid"] for n in body["nodes"]}
    assert all(e["source"] in uids and e["target"] in uids for e in body["edges"])
    # Synthetic has 4 systems: each is its own territory, none is "smaller".
    ids = [t["id"] for t in body["territories"]]
    assert "other" not in ids and sum(t["systems"] for t in body["territories"]) == 4
    assert {n["territory"] for n in body["nodes"]} <= set(ids)
    assert body["comments"] > 0 and any(n["comments"] for n in body["nodes"])
    assert body["bots"] == 1 and not body["bots_shown"]  # ci-bot
    assert len(with_bots["nodes"]) == len(body["nodes"]) + 1 and with_bots["bots_shown"]
