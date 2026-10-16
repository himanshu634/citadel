"""The embedder interface, its settings and the fake used in tests."""

from __future__ import annotations

import sys
import types

import pytest
from brain.config import get_settings
from brain.embeddings import (
    EmbeddingUnavailable,
    FastEmbedEmbedder,
    get_embedder,
    set_embedder,
)
from brain.testing import FakeEmbedder


@pytest.fixture(autouse=True)
def _reset_embedder():
    yield
    get_settings.cache_clear()
    set_embedder(None)


def test_fake_embedder_is_deterministic_and_normalised():
    e = FakeEmbedder(dim=16)
    a, b = e.passages(["Login breaks after token refresh", "login breaks after token refresh"])
    assert a == b and abs(sum(x * x for x in a) - 1.0) < 1e-6 and len(a) == 16


def test_fake_embedder_empty_text_is_a_zero_vector_and_query_matches_passages():
    e = FakeEmbedder(dim=8)
    assert e.passages([""]) == [[0.0] * 8]
    assert e.query("token refresh") == e.passages(["token refresh"])[0]


def test_session_default_is_no_embedder():
    # brain.testing sets EMBEDDING_PROVIDER=none for the whole run: no test loads the real model.
    assert get_embedder() is None


def test_provider_none_gives_no_embedder(embeddings_off):
    assert get_embedder() is None


def test_set_embedder_overrides_and_resets():
    fake = FakeEmbedder()
    set_embedder(fake)
    assert get_embedder() is fake
    set_embedder(None)
    assert get_embedder() is not fake


def test_fastembed_provider_builds_one_lazy_instance(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")
    monkeypatch.setenv("EMBEDDING_MODEL", "some/model")
    monkeypatch.setenv("EMBEDDING_DIM", "384")
    get_settings.cache_clear()
    set_embedder(None)
    e = get_embedder()  # building it must not load the model
    assert isinstance(e, FastEmbedEmbedder) and (e.model, e.dim) == ("some/model", 384)
    assert get_embedder() is e


def test_fastembed_dimension_mismatch_is_a_sentence(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DIM", "384")
    get_settings.cache_clear()
    e = FastEmbedEmbedder("BAAI/bge-base-en-v1.5", dim=384)
    with pytest.raises(EmbeddingUnavailable, match="768.*EMBEDDING_DIM=384"):
        e.check_dim(768)  # the model's real dimension, checked after load


def _fake_fastembed(monkeypatch, engine_class):
    module = types.ModuleType("fastembed")
    module.TextEmbedding = engine_class
    monkeypatch.setitem(sys.modules, "fastembed", module)


def test_fastembed_load_failure_is_a_sentence(monkeypatch):
    class Broken:
        def __init__(self, *args, **kwargs):
            raise OSError("no network")

    _fake_fastembed(monkeypatch, Broken)
    with pytest.raises(EmbeddingUnavailable, match="Could not load embedding model m: no network"):
        FastEmbedEmbedder("m", dim=4).query("hello")


def test_fastembed_uses_passage_and_query_embed_and_checks_dim_on_load(monkeypatch):
    np = pytest.importorskip("numpy")  # a fastembed dependency: vectors come back as arrays

    class Engine:
        embedding_size = 2

        def __init__(self, model_name, cache_dir):
            self.cache_dir = cache_dir

        def passage_embed(self, texts):
            return (np.array([1.0, len(t)]) for t in texts)

        def query_embed(self, text):
            return iter([np.array([2.0, len(text)])])

    _fake_fastembed(monkeypatch, Engine)
    e = FastEmbedEmbedder("m", dim=2)
    assert e.passages(["ab", "c"]) == [[1.0, 2.0], [1.0, 1.0]]
    assert e.query("abc") == [2.0, 3.0]
    with pytest.raises(EmbeddingUnavailable, match="EMBEDDING_DIM=3"):
        FastEmbedEmbedder("m", dim=3).query("x")
