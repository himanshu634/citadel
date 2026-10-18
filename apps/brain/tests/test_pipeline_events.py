"""Build events: the stages fetch/ingest/schema report to an `on_event` callback."""

from __future__ import annotations

import inspect

import pytest
from brain import adapters, config, db, pipeline, schema
from brain.embeddings import set_embedder
from brain.events import BuildEvent, BuildStopped
from brain.testing import FakeEmbedder, needs_graph, synthetic_company, write_company

SLUG = "test_events"


@pytest.fixture
def tmp_root(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    (tmp_path / "companies").mkdir()
    return tmp_path


@pytest.fixture
def events_company(tmp_root):
    write_company(synthetic_company(SLUG))
    yield SLUG
    db.delete_graph(SLUG)


@pytest.fixture
def events_company_missing_folder(tmp_root):
    cfg = synthetic_company(SLUG)
    cfg.sources[0].path = tmp_root / "no_such_folder"
    write_company(cfg)
    yield SLUG
    db.delete_graph(SLUG)


@pytest.fixture
def two_source_company(tmp_root):
    cfg = synthetic_company(SLUG)
    cfg.sources = [
        adapters.REGISTRY["local_docs"].source_model.model_validate(
            {"type": "local_docs", "path": "docs"}
        ),
        adapters.REGISTRY["canonical_jsonl"].source_model.model_validate(
            {"type": "canonical_jsonl", "path": "export"}
        ),
    ]
    write_company(cfg)
    return SLUG


class RecordingAdapter:
    """Stands in for a real adapter: records which source keys were fetched."""

    def __init__(self, real_name: str, fetched: list[str]):
        real = adapters.REGISTRY[real_name]
        self._real = real
        self.name = real.name
        self.source_model = real.source_model
        self._fetched = fetched

    def key(self, source):
        return self._real.key(source)

    def fetch(self, company, source, cache_dir, full=False):
        self._fetched.append(self.key(source))

    def records(self, company, source, cache_dir):  # unused by fetch
        raise NotImplementedError


@pytest.fixture
def fake_embedder():
    set_embedder(FakeEmbedder())
    yield
    set_embedder(None)


@needs_graph
def test_ingest_emits_stages_in_order(events_company, fake_embedder):
    seen: list[BuildEvent] = []
    report = pipeline.ingest(events_company, full=True, on_event=seen.append)
    assert [(e.stage, e.status) for e in seen] == [
        ("records", "running"),
        ("records", "done"),
        ("normalize", "done"),
        ("load", "running"),
        ("load", "done"),
        ("embed", "running"),
        ("embed", "running"),  # the count after the one batch
        ("embed", "done"),
    ]
    assert seen[1].count > 0 and seen[1].source.startswith("canonical_jsonl:")
    sourced = seen[:-3]
    assert all(e.slug == events_company and e.source == seen[0].source for e in sourced)
    assert sourced[-1].count > 0  # rows written for this source
    # the embed stage is the whole company's, after every source
    embedded = report.embed.embedded
    assert all(e.source is None for e in seen[-3:]) and embedded > 0
    assert [e.count for e in seen[-3:]] == [None, embedded, embedded]


@needs_graph
def test_ingest_without_embeddings_ends_with_a_skipped_embed(events_company, embeddings_off):
    seen: list[BuildEvent] = []
    report = pipeline.ingest(events_company, full=True, on_event=seen.append)
    assert (seen[-1].stage, seen[-1].status) == ("embed", "skipped")
    assert report.embed.embedded == 0 and "EMBEDDING_PROVIDER" in report.embed.skipped_reason


@needs_graph
def test_ingest_completes_when_the_model_raises(events_company):
    class Broken(FakeEmbedder):
        def passages(self, texts):
            raise RuntimeError("segfault in the runtime")

    set_embedder(Broken())
    try:
        seen: list[BuildEvent] = []
        report = pipeline.ingest(events_company, full=True, on_event=seen.append)
    finally:
        set_embedder(None)
    assert (seen[-1].stage, seen[-1].status) == ("embed", "skipped")
    assert "segfault in the runtime" in seen[-1].message == report.embed.skipped_reason
    assert sum(report.load.written.values()) > 0  # the sources were still loaded


@needs_graph
def test_missing_folder_is_skipped(events_company_missing_folder):
    seen: list[BuildEvent] = []
    pipeline.ingest(events_company_missing_folder, on_event=seen.append)
    records = [e for e in seen if e.stage == "records"]
    assert records[-1].status == "skipped" and records[-1].message


def test_fetch_keys_filter(monkeypatch, two_source_company):
    fetched: list[str] = []
    monkeypatch.setitem(adapters.REGISTRY, "local_docs", RecordingAdapter("local_docs", fetched))
    monkeypatch.setitem(
        adapters.REGISTRY, "canonical_jsonl", RecordingAdapter("canonical_jsonl", fetched)
    )
    seen: list[BuildEvent] = []
    pipeline.fetch(two_source_company, keys={"local_docs:docs"}, on_event=seen.append)
    assert fetched == ["local_docs:docs"]
    assert [(e.stage, e.status, e.source) for e in seen] == [
        ("fetch", "running", "local_docs:docs"),
        ("fetch", "done", "local_docs:docs"),
    ]


def test_fetch_failure_emits_failed_and_reraises(monkeypatch, two_source_company):
    class Boom(RecordingAdapter):
        def fetch(self, company, source, cache_dir, full=False):
            raise RuntimeError("rate limited")

    monkeypatch.setitem(adapters.REGISTRY, "local_docs", Boom("local_docs", []))
    seen: list[BuildEvent] = []
    with pytest.raises(RuntimeError, match="rate limited"):
        pipeline.fetch(two_source_company, only="local_docs", on_event=seen.append)
    assert (seen[-1].stage, seen[-1].status, seen[-1].message) == (
        "fetch",
        "failed",
        "rate limited",
    )


@needs_graph
def test_apply_schema_emits_prepare(events_company):
    seen: list[BuildEvent] = []
    schema.apply_schema(events_company, on_event=seen.append)
    assert [(e.stage, e.status, e.source) for e in seen] == [
        ("prepare", "running", None),
        ("prepare", "done", None),
    ]


@needs_graph
def test_stop_from_callback(events_company):
    def stop(e):
        if e.stage == "load":
            raise BuildStopped

    with pytest.raises(BuildStopped):
        pipeline.ingest(events_company, full=True, on_event=stop)


def test_cli_path_unchanged():
    assert inspect.signature(pipeline.ingest).parameters["on_event"].default is None
    assert inspect.signature(pipeline.fetch).parameters["on_event"].default is None
    assert inspect.signature(schema.apply_schema).parameters["on_event"].default is None


@needs_graph
def test_an_incremental_ingest_backfills_missing_body_chunks(events_company, embeddings_off):
    """A graph built before work items had body chunks: the cursor skips the old items, so only
    the backfill can give them one."""
    pipeline.ingest(events_company, full=True)
    count = "MATCH (c:Chunk {kind: 'work_item'}) RETURN count(c)"
    assert db.run_text(events_company, count).result_set[0][0] == 16
    db.run_text(events_company, "MATCH (c:Chunk {kind: 'work_item'}) DETACH DELETE c")
    pipeline.ingest(events_company)
    assert db.run_text(events_company, count).result_set[0][0] == 16
