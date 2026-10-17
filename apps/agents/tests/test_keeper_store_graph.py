"""The Keeper's ledger on FalkorDB: what only the real graph can show (needs `make up`).

The shared ledger cases run on both stores in test_keeper_store.py. Each test here uses a
throwaway keeper_test_<hex> graph and deletes it afterwards.
"""

from __future__ import annotations

import uuid

import pytest
from agents.graphs import keeper_graph_name
from agents.keeper.model import gap_uid
from agents.keeper.store import KeeperStore, delete_keeper_graph
from brain import db
from brain.testing import needs_graph

pytestmark = needs_graph


@pytest.fixture
def slug():
    slug = f"test_{uuid.uuid4().hex[:8]}"
    yield slug
    delete_keeper_graph(slug)


def test_reads_of_a_missing_graph_are_empty(slug):
    store = KeeperStore(slug)
    assert store.read("ledger/gaps", {"statuses": ["open"], "limit": 5}) == []
    assert store.read("ledger/review_current", {}) == []
    assert keeper_graph_name(slug) not in db.client().list_graphs()


def test_delete_keeper_graph(slug):
    assert delete_keeper_graph(slug) is False
    store = KeeperStore(slug)
    params = {"uid": gap_uid(), "kind": "failed_question", "text": "x?", "norm": "x"}
    store.write("ledger/open_gap", "citadel_keeper", {**params, "now": "2026-10-17T10:00:00Z"})
    assert keeper_graph_name(slug) in db.client().list_graphs()
    assert delete_keeper_graph(slug) is True
    assert keeper_graph_name(slug) not in db.client().list_graphs()


def test_ledger_has_uid_indexes(slug):
    store = KeeperStore(slug)
    params = {"uid": gap_uid(), "kind": "failed_question", "text": "x?", "norm": "x"}
    store.write("ledger/open_gap", "citadel_keeper", {**params, "now": "2026-10-17T10:00:00Z"})
    rows = db.rows(db.client().select_graph(keeper_graph_name(slug)).query("CALL db.indexes()"))
    labels = {r["label"] for r in rows}
    assert {"Gap", "LogEntry", "Review"} <= labels
