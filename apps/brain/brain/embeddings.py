"""Text embeddings: the interface, its two providers and the process-wide embedder.

Why: the embed stage (writes Chunk.embedding) and the semantic search tool (embeds the question)
must use the same model, and the engine must keep working without one. Code asks `get_embedder()`
and gets None when embeddings are off (`EMBEDDING_PROVIDER=none`), so every caller has one place
to handle "no embeddings". Two providers:
- `fastembed` (default) runs a small ONNX model on this machine's CPU: no API key, no GPU, and no
  text leaves the machine. It is imported only when the model first loads, so importing this
  module is cheap.
- `gemini` calls Google's Gemini embedding API with GEMINI_API_KEY: no model in memory, but chunk
  text and questions go to Google (Google's terms keep paid use, credits included, out of
  product training).
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

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from brain import loader
from brain.chunking import text_hash
from brain.config import REPO_ROOT, get_settings
from brain.events import BuildEvent, OnEvent, noop

MODEL_CACHE = REPO_ROOT / "data" / "models"


class EmbeddingUnavailable(RuntimeError):
    """The embedding model cannot be used. The message is a sentence for a person."""


DEFAULT_MODEL = {"fastembed": "BAAI/bge-base-en-v1.5", "gemini": "gemini-embedding-2"}


def _check_dim(model: str, dim: int, actual: int) -> None:
    if actual != dim:
        raise EmbeddingUnavailable(
            f"Embedding model {model} produces {actual}-dimensional vectors but "
            f"EMBEDDING_DIM={dim}. Set EMBEDDING_DIM={actual} (and rebuild the vector "
            "index), or choose a model with that size."
        )


class Embedder(Protocol):
    """Turns text into vectors of `dim` floats. Passages and queries are embedded differently
    (retrieval models take an instruction on the query side), so they are separate calls.
    An embedder may also have `start_message`: what the build page shows while the embed stage
    starts (else `LOADING_MODEL`)."""

    model: str
    dim: int

    def passages(self, texts: list[str]) -> list[list[float]]: ...

    def query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    """fastembed's TextEmbedding. The model loads on the first call (and downloads into
    data/models the first time); `dim` is checked against the loaded model right away.

    A failed load (no network, a wrong EMBEDDING_DIM) is remembered for `RETRY_AFTER` seconds:
    every call in that time raises the same sentence at once instead of trying the download
    again (semantic search asks on every question). One thread loads; a question (`query`)
    that comes while it does is refused with a sentence rather than kept waiting for a
    download, while the embed stage (`passages`) waits for it."""

    RETRY_AFTER = 300.0  # seconds a failed load is remembered
    start_message = "Loading the embedding model (the first run downloads about 0.2 GB)"

    def __init__(self, model: str, dim: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.model = model
        self.dim = dim
        self._engine: Any = None
        self._lock = threading.Lock()
        self._clock = clock
        self._failed: tuple[float, str] | None = None  # when the last load failed, and why

    @property
    def loaded(self) -> bool:
        """The model is in memory (a call now would not load or download it)."""
        return self._engine is not None

    def check_dim(self, actual: int) -> None:
        _check_dim(self.model, self.dim, actual)

    def _raise_recent_failure(self) -> None:
        if self._failed is not None and self._clock() - self._failed[0] < self.RETRY_AFTER:
            raise EmbeddingUnavailable(self._failed[1])

    def _load(self, wait: bool) -> Any:
        if self._engine is not None:
            return self._engine
        self._raise_recent_failure()
        if not self._lock.acquire(blocking=wait):
            raise EmbeddingUnavailable(
                f"Embedding model {self.model} is still loading (the first run downloads it). "
                "Try again in a minute."
            )
        try:
            if self._engine is None:
                self._raise_recent_failure()  # the load this thread waited on failed
                try:
                    self._engine = self._new_engine()
                except EmbeddingUnavailable as exc:
                    self._failed = (self._clock(), str(exc))
                    raise
                self._failed = None
            return self._engine
        finally:
            self._lock.release()

    def _new_engine(self) -> Any:
        try:
            from fastembed import TextEmbedding

            engine = TextEmbedding(self.model, cache_dir=str(MODEL_CACHE))
            size = engine.embedding_size
        except Exception as exc:
            raise EmbeddingUnavailable(
                f"Could not load embedding model {self.model}: {exc}"
            ) from exc
        self.check_dim(size)
        return engine

    def passages(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._load(wait=True).passage_embed(texts)]

    def query(self, text: str) -> list[float]:
        return next(iter(self._load(wait=False).query_embed(text))).tolist()


GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"


class GeminiEmbedder:
    """Google's Gemini embedding API (`batchEmbedContents`), asked for `dim`-sized vectors so
    the vector index keeps its size (768 is one of the sizes Google recommends).

    gemini-embedding-2 takes the retrieval task as a prefix of the text; gemini-embedding-001
    takes it as `taskType`. Vectors are L2-normalised here, since 001 returns shortened vectors
    unnormalised. Rate limits and server errors are retried with backoff; every other failure
    is an `EmbeddingUnavailable` sentence, so the embed stage skips with it and semantic search
    reports it."""

    BATCH = 100  # texts per request
    TRIES = 4  # attempts per request on a rate limit or a server error
    RETRY_STATUS = {429, 500, 502, 503, 504}

    def __init__(
        self,
        model: str,
        dim: int,
        api_key: str | None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model
        self.dim = dim
        self.start_message = f"Embedding with {model} (Google Gemini API)"
        self._key = api_key
        self._client = client or httpx.Client(timeout=60.0)
        self._sleep = sleep

    def passages(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "RETRIEVAL_DOCUMENT", "title: none | text: {}")

    def query(self, text: str) -> list[float]:
        return self._embed([text], "RETRIEVAL_QUERY", "task: search result | query: {}")[0]

    def _embed(self, texts: list[str], task: str, prefix: str) -> list[list[float]]:
        if not self._key:
            raise EmbeddingUnavailable(
                "GEMINI_API_KEY is not set, so the Gemini embedding model cannot be used. Set "
                "it in .env, or set EMBEDDING_PROVIDER=fastembed."
            )
        old = self.model.endswith("embedding-001")  # takes taskType, not a text prefix
        out: list[list[float]] = []
        for i in range(0, len(texts), self.BATCH):
            requests = [
                {
                    "model": f"models/{self.model}",
                    "content": {"parts": [{"text": t if old else prefix.format(t)}]},
                    "outputDimensionality": self.dim,
                    **({"taskType": task} if old else {}),
                }
                for t in texts[i : i + self.BATCH]
            ]
            out += [_normalised(v) for v in self._post(requests)]
        return out

    def _post(self, requests: list[dict[str, Any]]) -> list[list[float]]:
        url = f"{GEMINI_API}/models/{self.model}:batchEmbedContents"
        for attempt in range(self.TRIES):
            try:
                r = self._client.post(
                    url, json={"requests": requests}, headers={"x-goog-api-key": self._key or ""}
                )
            except httpx.HTTPError as exc:
                raise EmbeddingUnavailable(
                    f"Could not reach the Gemini API for embedding model {self.model}: {exc}"
                ) from exc
            if r.status_code in self.RETRY_STATUS and attempt < self.TRIES - 1:
                self._sleep(2.0**attempt)
                continue
            if r.status_code != 200:
                raise EmbeddingUnavailable(self._error(r))
            vectors = [e["values"] for e in r.json()["embeddings"]]
            for v in vectors:
                _check_dim(self.model, self.dim, len(v))
            return vectors
        raise AssertionError("unreachable")  # the last attempt returns or raises

    def _error(self, r: httpx.Response) -> str:
        try:
            message = r.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = r.text[:200]
        sentence = f"Gemini embedding model {self.model} failed (HTTP {r.status_code}): {message}"
        if r.status_code == 404:
            sentence += " Set EMBEDDING_MODEL to a Gemini embedding model, e.g. gemini-embedding-2."
        return sentence


def _normalised(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v] if norm else v


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
            provider = settings.embedding_provider
            model = settings.embedding_model or DEFAULT_MODEL[provider]
            if provider == "gemini":
                _default = GeminiEmbedder(model, settings.embedding_dim, settings.gemini_api_key)
            else:
                _default = FastEmbedEmbedder(model, settings.embedding_dim)
        return _default


def is_warm() -> bool:
    """An embedder already exists in this process and its model is loaded, so embedding now
    costs no model load. Never builds or loads one (the Archivist asks on the Ask path). An
    embedder with no `loaded` flag (Gemini, test fakes) has nothing to load: warm once built."""
    e = _override
    if e is None:
        if get_settings().embedding_provider == "none":
            return False
        e = _default
    return e is not None and bool(getattr(e, "loaded", True))


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
    "Set EMBEDDING_PROVIDER=fastembed (or gemini) and run make embed."
)


# On the stage's first event, before any model call, unless the embedder has its own
# `start_message`: the first load (and download) of a local model takes a while.
LOADING_MODEL = FastEmbedEmbedder.start_message

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
    sources: list[str] | None = None,
) -> EmbedReport:
    """Embed every chunk of brain_<slug> whose text or model changed since it was embedded.

    `embedder` None means `get_embedder()`. With no embedder, or a model that cannot run, the
    stage is skipped with the reason (vectors written before the failure stay). `everything`
    marks every chunk pending first, so each is embedded exactly once more. `sources` limits
    the stage to the chunks of those work items or documents (what the Archivist just loaded).
    """
    emit = on_event or noop
    report = EmbedReport()
    e = embedder if embedder is not None else get_embedder()
    if e is None:
        return _skip(slug, report, EMBEDDINGS_OFF, emit)
    emit(BuildEvent(slug, "embed", "running", message=getattr(e, "start_message", LOADING_MODEL)))
    if everything:
        loader.clear_embedded(slug)
    done: set[str] = set()
    reported: float | None = None  # when the last progress event went out
    while rows := loader.chunks_to_embed(slug, e.model, batch, sources):
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
        if written == 0:  # the same batch would come back: stop, and say so
            reason = (
                f"No vectors were stored for {len(rows)} chunks (were they deleted meanwhile?)."
            )
            return _skip(slug, report, reason, emit)
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
