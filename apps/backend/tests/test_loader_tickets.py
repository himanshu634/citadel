"""Ticket fields and edges in the loader: priority rank, due dates, ASSIGNED_TO replacement,
BLOCKS pruned by origin, and links resolved by url."""

from __future__ import annotations

from datetime import date

import pytest
from brain import db, loader, schema
from brain.canonical import (
    ALLOWED_LINKS,
    URL_LINKS,
    Link,
    Person,
    WorkItem,
    person_uid,
    url_ref,
)
from conftest import needs_graph

SLUG = "test_tickets"
ORIGIN = "linear:x"


def ticket(uid: str, **kw) -> WorkItem:
    fields = {
        "kind": "ticket",
        "title": uid,
        "state": "Todo",
        "status_category": "todo",
        "created_at": "2026-10-01T00:00:00Z",
    }
    return WorkItem(uid=uid, **{**fields, **kw})


def blocks(a: str, b: str) -> Link:
    return Link(
        rel="BLOCKS",
        from_uid=a,
        from_label="WorkItem",
        to_uid=b,
        to_label="WorkItem",
        source=ORIGIN,
    )


@pytest.fixture
def graph():
    db.delete_graph(SLUG)
    schema.apply_schema(SLUG)
    yield SLUG
    db.delete_graph(SLUG)


def rows(cypher: str, **params):
    """Ad-hoc read of the test graph (test-only Cypher, so it bypasses the named queries)."""
    return db.rows(db.run_text(SLUG, cypher, params))


def assignees(uid: str) -> list[str]:
    found = rows(
        "MATCH (p:Person)-[:ASSIGNED_TO]->(w:WorkItem {uid: $uid}) RETURN p.uid AS p ORDER BY p",
        uid=uid,
    )
    return [r["p"] for r in found]


def blocking() -> set[tuple[str, str]]:
    found = rows("MATCH (a)-[:BLOCKS]->(b) RETURN a.uid AS a, b.uid AS b")
    return {(r["a"], r["b"]) for r in found}


@needs_graph
def test_ticket_properties_written(graph):
    loader.load(
        SLUG,
        [
            ticket("t:1", key="ENG-1", priority="urgent", due_date=date(2026, 11, 6)),
            ticket("t:2"),
        ],
    )
    one, two = (
        rows(
            "MATCH (w:WorkItem {uid: $uid}) RETURN w.key AS key, w.status_category AS cat, "
            "w.priority AS priority, w.priority_rank AS rank, w.due_date AS due, "
            "w.due_ts AS due_ts",
            uid=uid,
        )[0]
        for uid in ("t:1", "t:2")
    )
    assert one["key"] == "ENG-1" and one["cat"] == "todo" and one["priority"] == "urgent"
    assert one["rank"] == 1
    assert one["due"] == "2026-11-06" and one["due_ts"] == 1793923200
    assert two["priority"] is None and two["rank"] == 5 and two["due"] is None


@needs_graph
def test_reassigning_replaces_assignee(graph):
    people = [Person(login="alice"), Person(login="bob")]
    loader.load(SLUG, [*people, ticket("t:1", assignees=["alice"])])
    loader.load(SLUG, [*people, ticket("t:1", assignees=["bob"])])
    assert assignees("t:1") == [person_uid("bob")]


@needs_graph
def test_several_assignees_and_unknown_person(graph):
    people = [Person(login="alice"), Person(login="bob")]
    report = loader.load(SLUG, [*people, ticket("t:1", assignees=["alice", "bob", "ghost"])])
    assert assignees("t:1") == [person_uid("alice"), person_uid("bob")]  # ghost has no node
    assert report.written["load/assigned_to"] == 1  # items matched, not edges


@needs_graph
def test_unassigning_removes_edge(graph):
    people = [Person(login="alice")]
    loader.load(SLUG, [*people, ticket("t:1", assignees=["alice"])])
    report = loader.load(SLUG, [*people, ticket("t:1", assignees=[])])
    assert assignees("t:1") == []
    assert report.dropped["load/assigned_to"] == 0  # the item was matched, not dropped


@needs_graph
def test_assignees_none_keeps_edges(graph):
    people = [Person(login="alice")]
    loader.load(SLUG, [*people, ticket("t:1", assignees=["alice"])])
    loader.load(SLUG, [*people, ticket("t:1", assignees=None)])
    assert assignees("t:1") == [person_uid("alice")]


@needs_graph
def test_prune_only_touches_its_origin(graph):
    items = [ticket(u) for u in ("t:a", "t:b", "t:c", "t:d")]
    loader.load(SLUG, [*items, blocks("t:a", "t:b")], origin=ORIGIN)
    loader.load(SLUG, [*items, blocks("t:c", "t:d")], origin="other")
    assert blocking() == {("t:a", "t:b"), ("t:c", "t:d")}
    loader.load(SLUG, items, origin=ORIGIN)
    assert blocking() == {("t:c", "t:d")}


@needs_graph
def test_prune_keeps_edges_in_this_load(graph):
    items = [ticket(u) for u in ("t:a", "t:b", "t:c")]
    loader.load(SLUG, [*items, blocks("t:a", "t:b"), blocks("t:b", "t:c")], origin=ORIGIN)
    loader.load(SLUG, [*items, blocks("t:b", "t:c")], origin=ORIGIN)
    assert blocking() == {("t:b", "t:c")}


@needs_graph
def test_load_without_origin_never_prunes(graph):
    items = [ticket(u) for u in ("t:a", "t:b")]
    loader.load(SLUG, [*items, blocks("t:a", "t:b")], origin=ORIGIN)
    loader.load(SLUG, items)
    assert blocking() == {("t:a", "t:b")}


@needs_graph
def test_mentions_by_url_resolves_target(graph):
    pr = WorkItem(
        uid="github:o/r:pr:1",
        kind="pull_request",
        title="Fix it",
        state="merged",
        created_at="2026-10-01T00:00:00Z",
        url="https://github.com/o/r/pull/1",
    )
    mention = Link(
        rel="MENTIONS",
        from_uid="t:1",
        from_label="WorkItem",
        to_uid=url_ref(pr.url),
        to_label="WorkItem",
    )
    lost = Link(
        rel="MENTIONS",
        from_uid="t:1",
        from_label="WorkItem",
        to_uid=url_ref("https://github.com/o/r/pull/999"),
        to_label="WorkItem",
    )
    report = loader.load(SLUG, [ticket("t:1"), pr, mention, lost])
    found = rows("MATCH (:WorkItem {uid: 't:1'})-[:MENTIONS]->(b) RETURN b.uid AS uid")
    assert [r["uid"] for r in found] == [pr.uid]
    query = "load/link_mentions_workitem_workitem_by_url"
    assert report.written[query] == 1
    assert report.dropped[query] == 1


def test_link_queries_cover_allowed_links():
    assert set(loader.LINK_QUERIES) == ALLOWED_LINKS
    assert set(loader.URL_LINK_QUERIES) == URL_LINKS
