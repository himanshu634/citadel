"""API test fixtures: a throwaway companies/ folder and a client that never touches FalkorDB.

The client's job runner uses fake steps that wait at `gate` (inside prepare) until a test opens
it, so a build stays running for as long as a test needs.
"""

from __future__ import annotations

import threading

import pytest
from brain import config, registry
from brain.agents.history import MemoryChatStore
from brain.api import create_app
from brain.jobs import JobRunner
from conftest import FakeSteps, synthetic_company
from fastapi.testclient import TestClient


@pytest.fixture
def api_root(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    (tmp_path / "companies").mkdir()
    return tmp_path


@pytest.fixture(autouse=True)
def no_graph(monkeypatch):
    """Unit tests must not need FalkorDB: every company reads as never built, and no slug has
    graphs left behind."""
    monkeypatch.setattr("brain.api.companies.status_of", lambda slug: ("empty", None))
    monkeypatch.setattr("brain.db.company_graphs", lambda slug: [])


@pytest.fixture(autouse=True)
def history(monkeypatch):
    """Ask runs record into an in-memory history, never into a real agent_<slug> graph."""
    store = MemoryChatStore()
    monkeypatch.setattr("brain.api.ask.graph_history", lambda slug: store)
    return store


@pytest.fixture
def gate():
    g = threading.Event()
    yield g
    g.set()  # never leave a worker blocked


@pytest.fixture
def runner(tmp_path, gate):
    return JobRunner(steps=FakeSteps(gate=gate), jobs_dir=tmp_path / "jobs")


@pytest.fixture
def client(runner):
    return TestClient(create_app(runner))


def write(root, slug: str, name: str) -> None:
    registry.write_new(synthetic_company(slug).model_copy(update={"name": name}))
