"""semantic_search over the FakeEmbedder's Chunk vectors (needs `make up`)."""

from __future__ import annotations

import pytest
from brain import tools
from brain.embeddings import EmbeddingUnavailable, get_embedder


def test_finds_a_comment_by_its_words_and_cites_its_work_item(embedded_graph):
    # erin's comment on PR 3 (comment 3 in generate.py):
    # "Rounding is off by a cent for annual plans."
    hits = tools.semantic_search(embedded_graph, text="rounding off by a cent on annual plans")
    assert hits[0].uid == "synthetic:pr:3"  # cited by its PR, not by the chunk
    assert hits[0].chunk_uid in {"chunk:synthetic:comment:3", "chunk:synthetic:pr:3:body"}
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
