"""The Gemini embedding provider, against a mocked HTTP transport: no test calls Google."""

from __future__ import annotations

import json
import math

import httpx
import pytest
from brain import embeddings
from brain.config import get_settings
from brain.embeddings import EmbeddingUnavailable, GeminiEmbedder, get_embedder, set_embedder


@pytest.fixture(autouse=True)
def _reset_embedder():
    yield
    get_settings.cache_clear()
    set_embedder(None)


class Google:
    """A fake batchEmbedContents: records each request and answers with `respond`."""

    def __init__(self, respond=None) -> None:
        self.requests: list[httpx.Request] = []
        self.respond = respond or self.vectors

    def vectors(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        dim = body["requests"][0].get("outputDimensionality", 3)
        # one un-normalised vector per text: [len(text), 0, 0, ...] scaled by 2
        out = [{"values": [2.0 * len(r["content"]["parts"][0]["text"])] + [0.0] * (dim - 1)}
               for r in body["requests"]]  # fmt: skip
        return httpx.Response(200, json={"embeddings": out})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.respond(request)

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]


def gemini(google: Google, model: str = "gemini-embedding-2", dim: int = 4, **kw) -> GeminiEmbedder:
    client = httpx.Client(transport=httpx.MockTransport(google))
    return GeminiEmbedder(
        model, dim, kw.pop("api_key", "k"), client=client, sleep=lambda s: None, **kw
    )


def test_passages_and_query_use_the_retrieval_prefixes_of_gemini_embedding_2():
    google = Google()
    e = gemini(google)
    assert e.passages(["Retry failed charges"]) == [[1.0, 0.0, 0.0, 0.0]]  # normalised
    assert e.query("why do charges fail") == [1.0, 0.0, 0.0, 0.0]
    first, second = google.bodies()
    doc = first["requests"][0]
    assert doc["model"] == "models/gemini-embedding-2"
    assert doc["content"]["parts"][0]["text"] == "title: none | text: Retry failed charges"
    assert doc["outputDimensionality"] == 4 and "taskType" not in doc
    q = second["requests"][0]["content"]["parts"][0]["text"]
    assert q == "task: search result | query: why do charges fail"
    request = google.requests[0]
    assert request.url.path == "/v1beta/models/gemini-embedding-2:batchEmbedContents"
    assert request.headers["x-goog-api-key"] == "k"


def test_gemini_embedding_001_takes_task_types_and_plain_text():
    google = Google()
    e = gemini(google, model="gemini-embedding-001")
    e.passages(["a"])
    e.query("b")
    doc, q = (b["requests"][0] for b in google.bodies())
    assert (doc["taskType"], doc["content"]["parts"][0]["text"]) == ("RETRIEVAL_DOCUMENT", "a")
    assert (q["taskType"], q["content"]["parts"][0]["text"]) == ("RETRIEVAL_QUERY", "b")


def test_vectors_are_l2_normalised():
    def skewed(request):
        n = len(json.loads(request.content)["requests"])
        return httpx.Response(200, json={"embeddings": [{"values": [3.0, 4.0]}] * n})

    (v,) = gemini(Google(skewed), dim=2).passages(["x"])
    assert v == [0.6, 0.8] and math.isclose(sum(x * x for x in v), 1.0)


def test_texts_go_in_batches_of_at_most_100():
    google = Google()
    vectors = gemini(google).passages([f"t{i}" for i in range(250)])
    assert len(vectors) == 250
    assert [len(b["requests"]) for b in google.bodies()] == [100, 100, 50]


def test_no_api_key_is_a_sentence():
    with pytest.raises(EmbeddingUnavailable, match="GEMINI_API_KEY is not set"):
        gemini(Google(), api_key=None).query("x")


def test_an_api_error_is_a_sentence_with_googles_message():
    def denied(request):
        error = {"error": {"code": 400, "message": "API key not valid.", "status": "INVALID"}}
        return httpx.Response(400, json=error)

    with pytest.raises(EmbeddingUnavailable, match="gemini-embedding-2.*API key not valid"):
        gemini(Google(denied)).passages(["x"])


def test_an_unknown_model_says_which_setting_to_change():
    def missing(request):
        return httpx.Response(404, json={"error": {"code": 404, "message": "not found"}})

    with pytest.raises(EmbeddingUnavailable, match="EMBEDDING_MODEL"):
        gemini(Google(missing), model="BAAI/bge-base-en-v1.5").query("x")


def test_rate_limits_are_retried_then_reported():
    calls = []

    def busy_then_ok(request):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, json={"error": {"message": "quota"}})
        return Google().vectors(request)

    assert gemini(Google(busy_then_ok)).query("x") == [1.0, 0.0, 0.0, 0.0]
    assert len(calls) == 3

    def always_busy(request):
        return httpx.Response(503, json={"error": {"message": "overloaded"}})

    google = Google(always_busy)
    with pytest.raises(EmbeddingUnavailable, match="overloaded"):
        gemini(google).query("x")
    assert len(google.requests) == GeminiEmbedder.TRIES


def test_a_network_failure_is_a_sentence():
    def offline(request):
        raise httpx.ConnectError("no route")

    with pytest.raises(EmbeddingUnavailable, match="no route"):
        gemini(Google(offline)).query("x")


def test_a_wrong_dimension_is_the_dim_sentence():
    def short(request):
        return httpx.Response(200, json={"embeddings": [{"values": [1.0, 0.0]}]})

    with pytest.raises(EmbeddingUnavailable, match="EMBEDDING_DIM=4"):
        gemini(Google(short)).query("x")


def test_provider_gemini_builds_one_with_the_default_model(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setenv("EMBEDDING_MODEL", "")  # unset: the provider's default
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    get_settings.cache_clear()
    set_embedder(None)
    e = get_embedder()
    assert isinstance(e, GeminiEmbedder)
    assert (e.model, e.dim) == ("gemini-embedding-2", 768)
    assert "Gemini" in e.start_message and get_embedder() is e


def test_fastembed_stays_the_default_model(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")
    monkeypatch.setenv("EMBEDDING_MODEL", "")
    get_settings.cache_clear()
    set_embedder(None)
    assert get_embedder().model == "BAAI/bge-base-en-v1.5"
    assert embeddings.FastEmbedEmbedder.start_message == embeddings.LOADING_MODEL
