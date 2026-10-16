"""API test fixtures: a throwaway companies/ folder and a client that never touches FalkorDB."""

from __future__ import annotations

import pytest
from brain import config, registry
from brain.api import create_app
from conftest import synthetic_company
from fastapi.testclient import TestClient


@pytest.fixture
def api_root(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    (tmp_path / "companies").mkdir()
    return tmp_path


@pytest.fixture(autouse=True)
def no_graph(monkeypatch):
    """Unit tests must not need FalkorDB: every company reads as never built."""
    monkeypatch.setattr("brain.api.companies.status_of", lambda slug: ("empty", None))


@pytest.fixture
def client():
    return TestClient(create_app())


def write(root, slug: str, name: str) -> None:
    registry.write_new(synthetic_company(slug).model_copy(update={"name": name}))
