"""Archived items and unresolved refs in the loader: round trip, ref resolution to MENTIONS,
supersession and what get_entity reports."""

from __future__ import annotations

import pytest
from brain import db, loader, schema, tools
from brain.canonical import Document, WorkItem
from brain.testing import needs_graph

SLUG = "archtest_load"
REF = "github:acme/w#812"


def item(uid: str, **kw) -> WorkItem:
    fields = {"kind": "issue", "title": uid, "state": "open", "created_at": "2026-10-01T00:00:00Z"}
    return WorkItem(uid=uid, **{**fields, **kw})


def mark(uid: str, ref: str | None = REF) -> list[dict]:
    return [{"uid": uid, "ref": ref, "archived_at": "2026-10-17T00:00:00Z", "request": "why?"}]


@pytest.fixture
def graph():
    db.delete_graph(SLUG)
    schema.apply_schema(SLUG)
    yield SLUG
    db.delete_graph(SLUG)


@needs_graph
def test_unresolved_refs_round_trip(graph):
    loader.load(SLUG, [item("a", unresolved_refs=[REF]), item("plain")])
    assert tools.get_entity(SLUG, "a").unresolved_refs == [REF]
    assert tools.get_entity(SLUG, "plain").unresolved_refs == []


@needs_graph
def test_resolve_refs_links_and_clears(graph):
    loader.load(SLUG, [item("a", unresolved_refs=[REF]), item("b")])
    assert loader.resolve_refs(SLUG) == 0  # nothing archived yet
    assert loader.mark_archived(SLUG, mark("b")) == 1
    assert loader.resolve_refs(SLUG) == 1
    a = tools.get_entity(SLUG, "a")
    assert a.unresolved_refs == []
    assert [(n.rel, n.direction, n.uid) for n in a.neighbours] == [("MENTIONS", "out", "b")]
    assert loader.resolve_refs(SLUG) == 0


@needs_graph
def test_resolve_refs_to_archived_document(graph):
    doc = Document(
        uid="d", path="docs/a.md", title="A", body="x", updated_at="2026-01-01T00:00:00Z"
    )
    loader.load(SLUG, [item("a", unresolved_refs=[REF]), doc])
    assert loader.mark_archived(SLUG, mark("d")) == 1
    assert loader.resolve_refs(SLUG) == 1
    assert tools.get_entity(SLUG, "a").neighbours[0].uid == "d"


@needs_graph
def test_mark_superseded(graph):
    loader.load(SLUG, [item("old"), item("new")])
    assert loader.mark_superseded(SLUG, "old", "new") is True
    old = tools.get_entity(SLUG, "old")
    assert old.superseded_by == "new"
    assert ("SUPERSEDED_BY", "out", "new") in [(n.rel, n.direction, n.uid) for n in old.neighbours]
    assert loader.mark_superseded(SLUG, "old", "missing") is False


@needs_graph
def test_get_entity_reports_archived(graph):
    loader.load(SLUG, [item("b"), item("c")])
    loader.mark_archived(SLUG, mark("b"))
    b, c = tools.get_entity(SLUG, "b"), tools.get_entity(SLUG, "c")
    assert b.archived is True and b.archived_at == "2026-10-17T00:00:00Z"
    assert c.archived is None and c.archived_at is None
