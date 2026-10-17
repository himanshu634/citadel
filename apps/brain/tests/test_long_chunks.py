"""Long work-item bodies and comments are cut into several chunks (needs `make up`).

The embedding model reads only the first 512 tokens of a text, so a long body or comment kept as
one chunk is searchable only by its start. Each piece is its own Chunk; the first keeps the uid a
whole text had, so comment counts, get_entity and the Graph page still see one chunk per text.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from brain import db, embeddings, loader, schema, tools
from brain.canonical import Comment, Person, WorkItem
from brain.testing import FakeEmbedder, needs_graph

pytestmark = needs_graph

SLUG = "test_long_chunks"
WHEN = datetime(2026, 9, 1, tzinfo=UTC)


def long_text(last_word: str) -> str:
    """Three paragraphs of about 900 characters: three chunks; `last_word` is only in the last."""
    return "\n\n".join([*(f"para{i} " * 150 for i in range(2)), "para2 " * 150 + last_word])


def records(body: str, comment: str) -> list:
    return [
        Person(login="alice", source="t"),
        Person(login="bob", source="t"),
        WorkItem(
            uid="t:pr:1", source="t", url="https://example.com/pull/1", kind="pull_request",
            number=1, title="Retry charges", body=body, state="open", created_at=WHEN,
            author_login="alice",
        ),
        Comment(
            uid="t:comment:1", source="t", url="https://example.com/pull/1#c1",
            work_item_uid="t:pr:1", author_login="bob", created_at=WHEN, body=comment,
        ),
    ]  # fmt: skip


CHUNKS = (
    "MATCH (c:Chunk)-[:FROM]->(:WorkItem {uid: 't:pr:1'}) "
    "RETURN c.uid, c.kind, c.idx, c.comment_uid, c.author_uid, c.created_at, c.url, "
    "c.text_hash IS NOT NULL ORDER BY c.uid"
)


@pytest.fixture
def graph():
    db.delete_graph(SLUG)
    schema.apply_schema(SLUG)
    yield SLUG
    embeddings.set_embedder(None)
    db.delete_graph(SLUG)


def chunks(slug: str) -> list[list]:
    return db.run_text(slug, CHUNKS).result_set


def test_long_body_and_comment_become_several_chunks(graph):
    loader.load(graph, records(long_text("zebrafinch"), long_text("quokka")))
    when = "2026-09-01T00:00:00Z"
    pr, c = "https://example.com/pull/1", "https://example.com/pull/1#c1"
    assert chunks(graph) == [
        ["chunk:t:comment:1", "comment", 0, "t:comment:1", "person:bob", when, c, True],
        ["chunk:t:comment:1:1", "comment", 1, "t:comment:1", "person:bob", when, c, True],
        ["chunk:t:comment:1:2", "comment", 2, "t:comment:1", "person:bob", when, c, True],
        ["chunk:t:pr:1:body", "work_item", 0, None, None, when, pr, True],
        ["chunk:t:pr:1:body:1", "work_item", 1, None, None, when, pr, True],
        ["chunk:t:pr:1:body:2", "work_item", 2, None, None, when, pr, True],
    ]


def test_shorter_text_loses_its_extra_chunks(graph):
    loader.load(graph, records(long_text("zebrafinch"), long_text("quokka")))
    loader.load(graph, records("Now short.", "Short too."))
    assert [r[0] for r in chunks(graph)] == ["chunk:t:comment:1", "chunk:t:pr:1:body"]


def test_a_blank_comment_keeps_its_one_chunk(graph):
    loader.load(graph, records("Body.", ""))
    assert "chunk:t:comment:1" in [r[0] for r in chunks(graph)]


def test_one_comment_is_still_counted_once(graph):
    loader.load(graph, records(long_text("zebrafinch"), long_text("quokka")))
    count = "MATCH (:Person {uid: 'person:bob'})-[r:COMMENTED_ON]->(:WorkItem) RETURN r.count"
    assert db.run_text(graph, count).result_set == [[1]]
    nodes = db.run(graph, "graph/nodes", {"labels": ["WorkItem"]}, read_only=True)
    assert [n["comments"] for n in nodes] == [1]
    entity = tools.get_entity(graph, uid="t:pr:1")
    chunk_neighbours = [n.uid for n in entity.neighbours if n.label == "Chunk"]
    assert chunk_neighbours == ["chunk:t:comment:1"]


def test_words_only_in_the_last_piece_are_found_once(graph):
    loader.load(graph, records(long_text("zebrafinch"), long_text("quokka")))
    fake = FakeEmbedder()
    assert embeddings.embed_pending(graph, fake).embedded == 6
    embeddings.set_embedder(fake)
    hits = tools.semantic_search(graph, text="zebrafinch")
    assert [h.uid for h in hits] == ["t:pr:1"]
    assert hits[0].chunk_uid == "chunk:t:pr:1:body:2"
    hits = tools.semantic_search(graph, text="quokka", kinds=["comment"])
    assert [(h.uid, h.chunk_uid) for h in hits] == [("t:pr:1", "chunk:t:comment:1:2")]


def test_backfill_splits_chunks_written_whole_before_splitting(graph):
    """A graph built before long text was split: one whole chunk per body and comment, with no
    idx. The backfill cuts them as a load would, and leaves nothing to do the second time."""
    loader.load(graph, records(long_text("zebrafinch"), long_text("quokka")))
    split = chunks(graph)
    db.run_text(graph, "MATCH (c:Chunk) WHERE c.idx > 0 DETACH DELETE c")
    db.run_text(
        graph,
        "MATCH (c:Chunk) REMOVE c.idx, c.comment_uid "
        "SET c.text = CASE c.kind WHEN 'comment' THEN $comment ELSE $body END",
        {"comment": long_text("quokka"), "body": "Retry charges\n\n" + long_text("zebrafinch")},
    )
    assert loader.backfill_chunks(graph) == 2
    assert chunks(graph) == split
    assert loader.backfill_chunks(graph) == 0
