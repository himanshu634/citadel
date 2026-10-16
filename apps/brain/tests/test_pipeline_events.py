"""Build events: the stages fetch/ingest/schema report to an `on_event` callback."""

from __future__ import annotations

import inspect

import pytest
from brain import adapters, config, db, pipeline, schema
from brain.events import BuildEvent, BuildStopped
from brain.testing import needs_graph, synthetic_company, write_company

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

    def fetch(self, company, source, cache_dir):
        self._fetched.append(self.key(source))

    def records(self, company, source, cache_dir):  # unused by fetch
        raise NotImplementedError


@needs_graph
def test_ingest_emits_stages_in_order(events_company):
    seen: list[BuildEvent] = []
    pipeline.ingest(events_company, full=True, on_event=seen.append)
    assert [(e.stage, e.status) for e in seen] == [
        ("records", "running"),
        ("records", "done"),
        ("normalize", "done"),
        ("load", "running"),
        ("load", "done"),
    ]
    assert seen[1].count > 0 and seen[1].source.startswith("canonical_jsonl:")
    assert all(e.slug == events_company and e.source == seen[0].source for e in seen)
    assert seen[-1].count > 0  # rows written for this source


@needs_graph
def test_missing_folder_is_skipped(events_company_missing_folder):
    seen: list[BuildEvent] = []
    pipeline.ingest(events_company_missing_folder, on_event=seen.append)
    assert seen[-1].stage == "records" and seen[-1].status == "skipped" and seen[-1].message


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
        def fetch(self, company, source, cache_dir):
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
