"""Text embeddings: the interface, the fastembed provider and the process-wide embedder.

Why: the embed stage (writes Chunk.embedding) and the semantic search tool (embeds the question)
must use the same model, and the engine must keep working without one. Code asks `get_embedder()`
and gets None when embeddings are off (`EMBEDDING_PROVIDER=none`), so every caller has one place
to handle "no embeddings". fastembed runs a small ONNX model on the CPU, so it needs no API key
and no GPU; it is imported only when the model first loads, so importing this module is cheap.
Tests swap in a fake with `set_embedder` (`brain.testing.FakeEmbedder`).

The embed stage (`embed_pending`) runs after ingest. A chunk is embedded again only when its
text, or the model, changed since: each vector is stored with the text hash and model it was
made from. A model that cannot run skips the stage with a reason; it never fails the build.
Its first `running` event says the model is loading (the first run downloads it), so the build
page tells why it waits. After a written batch it emits a `running` event with the count so far
(the first batch, then at most one a second: each event rewrites the build's snapshot), so the
build page shows progress and a build job's stop (raised from `on_event`) can act between
batches.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

from brain import loader
from brain.chunking import text_hash
from brain.config import REPO_ROOT, get_settings
from brain.events import BuildEvent, OnEvent, noop

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


# --- the embed stage --------------------------------------------------------------------------

EMBEDDINGS_OFF = (
    "Embeddings are off (EMBEDDING_PROVIDER=none), so semantic search finds nothing. "
    "Set EMBEDDING_PROVIDER=fastembed and run make embed."
)


# On the stage's first event, before any model call: the first load (and download) takes a while.
LOADING_MODEL = "Loading the embedding model (the first run downloads about 0.2 GB)"

PROGRESS_EVERY = 1.0  # seconds between two progress events of the embed stage
_clock = time.monotonic  # tests replace it to control which batches report


@dataclass
class EmbedReport:
    embedded: int = 0  # chunks given a new vector
    skipped_reason: str | None = None  # why the stage stopped early or did not run


def embed_pending(
    slug: str,
    embedder: Embedder | None = None,
    batch: int = 64,
    on_event: OnEvent | None = None,
    everything: bool = False,
) -> EmbedReport:
    """Embed every chunk of brain_<slug> whose text or model changed since it was embedded.

    `embedder` None means `get_embedder()`. With no embedder, or a model that cannot run, the
    stage is skipped with the reason (vectors written before the failure stay). `everything`
    marks every chunk pending first, so each is embedded exactly once more.
    """
    emit = on_event or noop
    report = EmbedReport()
    e = embedder if embedder is not None else get_embedder()
    if e is None:
        return _skip(slug, report, EMBEDDINGS_OFF, emit)
    emit(BuildEvent(slug, "embed", "running", message=LOADING_MODEL))
    if everything:
        loader.clear_embedded(slug)
    done: set[str] = set()
    reported: float | None = None  # when the last progress event went out
    while rows := loader.chunks_to_embed(slug, e.model, batch):
        uids = [r["uid"] for r in rows]
        if again := sorted(done.intersection(uids)):
            # stop rather than loop: the write did not make the chunk current
            reason = f"Chunk {again[0]} was still pending after its vector was written."
            return _skip(slug, report, reason, emit)
        try:
            vectors = list(e.passages([r["text"] for r in rows]))
        except EmbeddingUnavailable as exc:
            return _skip(slug, report, str(exc), emit)
        except Exception as exc:
            return _skip(slug, report, f"Embedding model {e.model} failed: {exc}", emit)
        if len(vectors) != len(rows):
            reason = (
                f"Embedding model {e.model} returned {len(vectors)} vectors for {len(rows)} chunks."
            )
            return _skip(slug, report, reason, emit)
        written = loader.set_embeddings(
            slug,
            [
                # chunks written before they carried text_hash get it here, or they stay pending
                {"uid": r["uid"], "vector": v, "text_hash": r["text_hash"] or text_hash(r["text"])}
                for r, v in zip(rows, vectors, strict=True)
            ],
            e.model,
        )
        report.embedded += written
        if written == 0:
            break  # nothing was stored, so the same batch would come back
        done.update(uids)
        # Progress, and the point where a build job's stop (raised by on_event) takes effect.
        now = _clock()
        if reported is None or now - reported >= PROGRESS_EVERY:
            reported = now
            emit(BuildEvent(slug, "embed", "running", count=report.embedded))
    emit(BuildEvent(slug, "embed", "done", count=report.embedded))
    return report


def _skip(slug: str, report: EmbedReport, reason: str, emit: OnEvent) -> EmbedReport:
    report.skipped_reason = reason
    count = report.embedded or None  # no "0 embedded" beside the reason
    emit(BuildEvent(slug, "embed", "skipped", count=count, message=reason))
    return report
