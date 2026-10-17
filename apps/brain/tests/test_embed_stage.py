"""The embed stage: Chunk nodes whose text changed since they were embedded get new vectors.

Each test loads the synthetic company into its own throwaway graph, because embedding writes to
every Chunk and the tests count what the next run still finds pending.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from brain import db, loader
from brain.canonical import Comment, WorkItem
from brain.embeddings import EmbeddingUnavailable, embed_pending
from brain.testing import FakeEmbedder, load_company, needs_graph, synthetic_company

pytestmark = needs_graph

SLUG = "test_embed_stage"


@pytest.fixture
def fresh_synthetic():
    db.delete_graph(SLUG)
    load_company(synthetic_company(SLUG))
    yield SLUG
    db.delete_graph(SLUG)


def count_chunks(slug: str) -> int:
    """Chunks with text: the ones the embed stage must embed."""
    rows = db.run_text(slug, "MATCH (c:Chunk) WHERE trim(c.text) <> '' RETURN count(c)")
    return rows.result_set[0][0]


def reload_comment(slug: str, uid: str, body: str) -> None:
    """Load one comment again with a new body, as an incremental ingest of an edit would."""
    loader.load(
        slug,
        [
            Comment(
                uid=uid,
                source="canonical_jsonl",
                work_item_uid="synthetic:pr:1",
                author_login="dave",
                created_at=datetime(2026, 2, 5, 12, tzinfo=UTC),
                body=body,
            )
        ],
    )


class Recording(FakeEmbedder):
    """A fake that remembers every text it was asked to embed."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.seen: list[str] = []

    def passages(self, texts: list[str]) -> list[list[float]]:
        self.seen += texts
        return super().passages(texts)


def test_embeds_every_chunk_once_then_nothing(fresh_synthetic):
    fake = FakeEmbedder()
    first = embed_pending(fresh_synthetic, fake)
    assert first.embedded == count_chunks(fresh_synthetic) > 0
    assert first.skipped_reason is None
    assert embed_pending(fresh_synthetic, fake).embedded == 0
    rows = db.run_text(
        fresh_synthetic,
        "MATCH (c:Chunk) RETURN count(c.embedding), count(c.embedded_hash), "
        "count(CASE WHEN c.embed_model = 'fake' THEN 1 END)",
    )
    assert rows.result_set[0] == [first.embedded] * 3


def test_edited_comment_reembeds_only_that_chunk(fresh_synthetic):
    embed_pending(fresh_synthetic, FakeEmbedder())
    reload_comment(fresh_synthetic, "synthetic:comment:1", body="new words entirely")
    fake = Recording()
    assert embed_pending(fresh_synthetic, fake).embedded == 1
    assert fake.seen == ["new words entirely"]


def test_new_model_reembeds_everything(fresh_synthetic):
    embed_pending(fresh_synthetic, FakeEmbedder(model="a"))
    report = embed_pending(fresh_synthetic, FakeEmbedder(model="b"))
    assert report.embedded == count_chunks(fresh_synthetic)


def test_no_provider_skips_with_a_reason(fresh_synthetic, embeddings_off):
    events = []
    report = embed_pending(fresh_synthetic, on_event=events.append)
    assert report.embedded == 0 and "EMBEDDING_PROVIDER" in report.skipped_reason
    assert events[-1].stage == "embed" and events[-1].status == "skipped"
    assert events[-1].message == report.skipped_reason


def test_events_report_running_then_done_with_the_count(fresh_synthetic):
    events = []
    report = embed_pending(fresh_synthetic, FakeEmbedder(), on_event=events.append)
    assert [(e.stage, e.status, e.source) for e in events] == [
        ("embed", "running", None),
        ("embed", "done", None),
    ]
    assert events[-1].count == report.embedded > 0


def test_everything_reembeds_each_chunk_once(fresh_synthetic):
    embed_pending(fresh_synthetic, FakeEmbedder())
    fake = Recording()
    report = embed_pending(fresh_synthetic, fake, batch=4, everything=True)
    assert report.embedded == count_chunks(fresh_synthetic) == len(fake.seen)  # no repeats


def test_unloadable_model_skips_not_fails(fresh_synthetic):
    class Broken(FakeEmbedder):
        def passages(self, texts):
            raise EmbeddingUnavailable("Could not load embedding model x: offline")

    events = []
    report = embed_pending(fresh_synthetic, Broken(), on_event=events.append)
    assert report.embedded == 0 and "offline" in report.skipped_reason
    assert (events[-1].stage, events[-1].status) == ("embed", "skipped")


def test_a_model_failing_midway_keeps_what_it_wrote(fresh_synthetic):
    class Flaky(FakeEmbedder):
        calls = 0

        def passages(self, texts):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("onnx went away")
            return super().passages(texts)

    report = embed_pending(fresh_synthetic, Flaky(), batch=4)
    assert report.embedded == 4 and "onnx went away" in report.skipped_reason
    assert embed_pending(fresh_synthetic, FakeEmbedder()).embedded == (
        count_chunks(fresh_synthetic) - 4
    )


def test_blank_chunks_are_never_embedded(fresh_synthetic):
    blank = WorkItem(
        uid="synthetic:issue:blank",
        source="canonical_jsonl",
        kind="issue",
        title="",
        body="  ",
        state="open",
        created_at=datetime(2026, 3, 1, tzinfo=UTC),
    )
    loader.load(fresh_synthetic, [blank])
    fake = Recording()
    report = embed_pending(fresh_synthetic, fake)
    assert report.embedded == count_chunks(fresh_synthetic) == len(fake.seen)
    assert all(t.strip() for t in fake.seen)
    rows = db.run_text(
        fresh_synthetic,
        "MATCH (c:Chunk {uid: 'chunk:synthetic:issue:blank:body'}) RETURN c.embedding IS NULL",
    )
    assert rows.result_set == [[True]]


def test_a_chunk_without_a_text_hash_is_embedded_once(fresh_synthetic):
    """Graphs built before chunks carried text_hash: embedding them must still terminate."""
    db.run_text(
        fresh_synthetic, "MATCH (c:Chunk {uid: 'chunk:synthetic:comment:1'}) REMOVE c.text_hash"
    )
    first = embed_pending(fresh_synthetic, FakeEmbedder())
    assert first.embedded == count_chunks(fresh_synthetic)
    assert embed_pending(fresh_synthetic, FakeEmbedder()).embedded == 0


def test_a_wrong_number_of_vectors_skips_and_keeps_what_was_written(fresh_synthetic):
    class Short(FakeEmbedder):
        calls = 0

        def passages(self, texts):
            self.calls += 1
            vectors = super().passages(texts)
            return vectors if self.calls == 1 else vectors[:-1]  # drops one from batch 2

    events = []
    report = embed_pending(fresh_synthetic, Short(), batch=4, on_event=events.append)
    assert report.embedded == 4 and "returned 3 vectors for 4 chunks" in report.skipped_reason
    assert (events[-1].stage, events[-1].status, events[-1].count) == ("embed", "skipped", 4)


def test_a_chunk_still_pending_after_its_write_stops_with_a_reason(fresh_synthetic, monkeypatch):
    # a write that reports success but changes nothing: the same batch comes back
    monkeypatch.setattr(loader, "set_embeddings", lambda slug, rows, model: len(rows))
    events = []
    report = embed_pending(fresh_synthetic, FakeEmbedder(), batch=4, on_event=events.append)
    assert report.embedded == 4 and "still pending" in report.skipped_reason
    assert (events[-1].stage, events[-1].status) == ("embed", "skipped")
