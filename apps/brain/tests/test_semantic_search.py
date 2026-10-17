"""semantic_search over the FakeEmbedder's Chunk vectors (needs `make up`)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from brain import db, embeddings, loader, schema, tools
from brain.canonical import Comment, Person, WorkItem
from brain.embeddings import EmbeddingUnavailable, get_embedder
from brain.testing import FakeEmbedder, needs_graph


def test_finds_a_comment_by_its_words_and_cites_its_work_item(embedded_graph):
    # erin's comment on PR 3 (comment 3 in generate.py):
    # "Rounding is off by a cent for annual plans."
    hits = tools.semantic_search(embedded_graph, text="rounding off by a cent on annual plans")
    assert hits[0].uid == "synthetic:pr:3"  # cited by its PR, not by the chunk
    # PR 3 has a body and two comment chunks; the best one is the comment that shares the words.
    assert hits[0].chunk_uid == "chunk:synthetic:comment:3"
    assert hits[0].label == "WorkItem" and hits[0].kind == "pull_request" and hits[0].number == 3
    assert hits == sorted(hits, key=lambda h: -h.similarity) and 0 <= hits[-1].similarity <= 1


def test_one_row_per_source_and_kinds_filter(embedded_graph):
    hits = tools.semantic_search(embedded_graph, text="managed postgres", limit=10)
    assert len({h.uid for h in hits}) == len(hits)
    docs = tools.semantic_search(embedded_graph, text="managed postgres", kinds=["document"])
    assert docs and all(h.label == "Document" for h in docs)
    assert all(h.kind == "document" and h.chunk_kind == "document" for h in docs)


def test_blank_text_returns_nothing_without_the_model(embedded_graph):
    assert tools.semantic_search(embedded_graph, text="   ") == []


def test_rows_never_carry_vectors(embedded_graph):
    row = tools.semantic_search(embedded_graph, text="invoice")[0].model_dump()
    assert not any(isinstance(v, list) and len(v) > 50 for v in row.values())


def test_provider_off_is_an_error_sentence(embedded_graph, embeddings_off):
    assert get_embedder() is None  # embeddings_off ran after embedded_graph set the fake
    with pytest.raises(EmbeddingUnavailable, match="Semantic search is off"):
        tools.semantic_search(embedded_graph, text="invoice")


BOT_COMMENT = "chunk:synthetic:comment:8"  # ci-bot's coverage report on PR 5 (generate.py)


def test_a_bot_comment_is_neither_embedded_nor_found(embedded_graph):
    has_no_vector = "MATCH (c:Chunk {uid: $uid}) RETURN c.embedding IS NULL"
    rows = db.run_text(embedded_graph, has_no_vector, {"uid": BOT_COMMENT})
    assert rows.result_set == [[True]]  # the chunk is there, without a vector
    hits = tools.semantic_search(embedded_graph, text="codecov report patch project coverage")
    assert all(h.chunk_uid != BOT_COMMENT for h in hits)


@needs_graph
def test_bot_text_embedded_before_the_filter_is_never_returned():
    """A bot-authored work item and a bot comment, embedded before bots were left out (their
    vectors are written directly): the embed stage skips them and search never returns them."""
    slug = "test_bot_text"
    db.delete_graph(slug)
    fake = FakeEmbedder()
    when = datetime(2026, 9, 1, tzinfo=UTC)

    def item(n: int, author: str, title: str) -> WorkItem:
        return WorkItem(
            uid=f"t:pr:{n}", source="t", kind="pull_request", number=n, title=title,
            state="open", created_at=when, author_login=author,
        )  # fmt: skip

    def comment(n: int, author: str, body: str) -> Comment:
        return Comment(uid=f"t:comment:{n}", source="t", work_item_uid="t:pr:1",
                       author_login=author, created_at=when, body=body)  # fmt: skip

    try:
        schema.apply_schema(slug)
        loader.load(
            slug,
            [
                Person(login="alice", source="t"),
                Person(login="renovate[bot]", is_bot=True, source="t"),
                item(1, "alice", "Retry failed charges"),
                item(2, "renovate[bot]", "Update dependency lodash, coverage report"),
                comment(1, "alice", "Retry once, then alert"),
                comment(2, "renovate[bot]", "Coverage report: lodash coverage up"),
            ],
        )
        human = {"chunk:t:pr:1:body", "chunk:t:comment:1"}
        assert {r["uid"] for r in loader.chunks_to_embed(slug, fake.model, 100)} == human
        every_chunk = db.run_text(slug, "MATCH (c:Chunk) RETURN c.uid, c.text").result_set
        assert len(every_chunk) == 4
        rows = [{"uid": u, "vector": fake.query(t), "text_hash": None} for u, t in every_chunk]
        loader.set_embeddings(slug, rows, fake.model)
        embeddings.set_embedder(fake)
        hits = tools.semantic_search(slug, text="lodash coverage report", limit=10)
        assert hits and {h.chunk_uid for h in hits} <= human
    finally:
        embeddings.set_embedder(None)
        db.delete_graph(slug)
