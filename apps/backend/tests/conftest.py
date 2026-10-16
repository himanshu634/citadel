"""Fixtures for the backend's tests. Graph tests use a real FalkorDB (`make up`).

The helpers every package's tests share (`needs_graph`, `synthetic_company`, the synthetic graph)
come from `brain.testing`, a pytest plugin that the root pyproject loads. The fake build and the
second company are in `backend.testing`.
"""

from __future__ import annotations

import pytest
from backend.testing import second_company
from brain import db
from brain.testing import falkordb_up, load_company


@pytest.fixture(scope="session")
def second_graph():
    """brain_test_second loaded once per test run; deleted afterwards."""
    if not falkordb_up():
        pytest.skip("FalkorDB not reachable (make up)")
    slug = "test_second"
    db.delete_graph(slug)
    load_company(second_company(slug))
    yield slug
    db.delete_graph(slug)
