"""Text embeddings: the interface, the fastembed provider and the process-wide embedder.

Why: the embed stage (writes Chunk.embedding) and the semantic search tool (embeds the question)
must use the same model, and the engine must keep working without one. Code asks `get_embedder()`
and gets None when embeddings are off (`EMBEDDING_PROVIDER=none`), so every caller has one place
to handle "no embeddings". fastembed runs a small ONNX model on the CPU, so it needs no API key
and no GPU; it is imported only when the model first loads, so importing this module is cheap.
Tests swap in a fake with `set_embedder` (`brain.testing.FakeEmbedder`).
"""

from __future__ import annotations

import threading
from typing import Any, Protocol

from brain.config import REPO_ROOT, get_settings

MODEL_CACHE = REPO_ROOT / "data" / "models"


class EmbeddingUnavailable(RuntimeError):
    """The embedding model cannot be used. The message is a sentence for a person."""


class Embedder(Protocol):
    """Turns text into vectors of `dim` floats. Passages and queries are embedded differently
    (retrieval models take an instruction on the query side), so they are separate calls."""

    model: str
    dim: int

    def passages(self, texts: list[str]) -> list[list[float]]: ...

    def query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    """fastembed's TextEmbedding. The model loads on the first call (and downloads into
    data/models the first time); `dim` is checked against the loaded model right away."""

    def __init__(self, model: str, dim: int) -> None:
        self.model = model
        self.dim = dim
        self._engine: Any = None
        self._lock = threading.Lock()

    def check_dim(self, actual: int) -> None:
        if actual != self.dim:
            raise EmbeddingUnavailable(
                f"Embedding model {self.model} produces {actual}-dimensional vectors but "
                f"EMBEDDING_DIM={self.dim}. Set EMBEDDING_DIM={actual} (and rebuild the vector "
                "index), or choose a model with that size."
            )

    def _load(self) -> Any:
        with self._lock:
            if self._engine is None:
                try:
                    from fastembed import TextEmbedding

                    engine = TextEmbedding(self.model, cache_dir=str(MODEL_CACHE))
                    size = engine.embedding_size
                except Exception as exc:
                    raise EmbeddingUnavailable(
                        f"Could not load embedding model {self.model}: {exc}"
                    ) from exc
                self.check_dim(size)
                self._engine = engine
            return self._engine

    def passages(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._load().passage_embed(texts)]

    def query(self, text: str) -> list[float]:
        return next(iter(self._load().query_embed(text))).tolist()


_lock = threading.Lock()
_default: Embedder | None = None
_override: Embedder | None = None


def get_embedder() -> Embedder | None:
    """The embedder to use, or None when embeddings are off. One instance per process; an
    embedder given to `set_embedder` wins over the settings."""
    global _default
    if _override is not None:
        return _override
    settings = get_settings()
    if settings.embedding_provider == "none":
        return None
    with _lock:
        if _default is None:
            _default = FastEmbedEmbedder(settings.embedding_model, settings.embedding_dim)
        return _default


def set_embedder(e: Embedder | None) -> None:
    """Override the embedder (tests, callers with their own). None restores the settings-based
    default and forgets the instance built from the old settings."""
    global _default, _override
    with _lock:
        _override = e
        if e is None:
            _default = None
