"""Incremental-ingest cursor rules (pure, no database)."""

from datetime import UTC, datetime

import pytest
from brain import adapters, config, loader, pipeline
from brain.canonical import Change, Document, Person, WorkItem
from brain.embeddings import EmbedReport
from brain.events import BuildEvent
from brain.pipeline import next_cursor, select_new
from brain.testing import synthetic_company, write_company

CURSOR = datetime(2026, 8, 1, tzinfo=UTC)
NOW = datetime(2026, 10, 16, tzinfo=UTC)


def item(uid: str, created: str) -> WorkItem:
    return WorkItem(uid=uid, kind="issue", title=uid, state="open", created_at=created)


def change(uid: str, date: str) -> Change:
    return Change(uid=uid, sha=uid, date=date, subject="x")


def test_old_work_items_are_skipped_but_git_dated_records_always_load():
    records = [
        item("old", "2026-05-01T00:00:00Z"),
        item("new", "2026-09-01T00:00:00Z"),
        change("late_push", "2026-05-01T00:00:00Z"),  # committed in May, pushed after cursor
        Document(uid="d", path="a.md", title="a", updated_at="2026-05-01T00:00:00Z"),
        Person(login="alice"),
    ]
    kept = {r.uid for r in select_new(records, CURSOR)}
    assert kept == {"new", "late_push", "d", "person:alice"}
    assert {r.uid for r in select_new(records, None)} == {r.uid for r in records}


def test_git_dates_never_move_the_cursor_and_it_never_passes_now():
    skewed = change("future", "2030-01-01T00:00:00Z")  # a laptop with a bad clock
    assert next_cursor([skewed], CURSOR, NOW) == CURSOR
    assert next_cursor([item("n", "2026-09-01T00:00:00Z"), skewed], CURSOR, NOW) == datetime(
        2026, 9, 1, tzinfo=UTC
    )
    assert next_cursor([item("f", "2031-01-01T00:00:00Z")], None, NOW) == NOW
    assert next_cursor([], None, NOW) is None


def test_ingest_passes_source_key_as_origin(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    (tmp_path / "companies").mkdir()
    write_company(synthetic_company("test_origin"))
    origins: list[str | None] = []
    monkeypatch.setattr(loader, "get_cursor", lambda *a: None)
    monkeypatch.setattr(loader, "set_sync_state", lambda *a: None)

    def fake_load(slug, records, origin=None):
        origins.append(origin)
        return loader.LoadReport()

    monkeypatch.setattr(loader, "load", fake_load)
    pipeline.ingest("test_origin")
    assert len(origins) == 1 and origins[0].startswith("canonical_jsonl:")


class SyncStateSpy:
    """Stands in for the loader: a fixed cursor in, every written cursor recorded."""

    def __init__(self, monkeypatch, cursor: datetime | None) -> None:
        self.written: list[datetime | None] = []
        monkeypatch.setattr(loader, "get_cursor", lambda *a: cursor)
        monkeypatch.setattr(loader, "set_sync_state", lambda *a: self.written.append(a[3]))
        monkeypatch.setattr(loader, "load", lambda slug, records, origin=None: loader.LoadReport())
        monkeypatch.setattr(pipeline, "embed", lambda slug, on_event=None: EmbedReport())


class PartialAdapter:
    """A source whose cache holds some records but whose fetch has not finished."""

    name = "canonical_jsonl"
    source_model = adapters.REGISTRY["canonical_jsonl"].source_model
    reason: str | None = "work_items: fetch run 20261018T000000 stopped at page 3"

    def key(self, source):
        return f"partial:{source.path.as_posix()}"

    def fetch(self, company, source, cache_dir, full=False):
        pass

    def incomplete(self, company, source, cache_dir):
        return self.reason

    def records(self, company, source, cache_dir):
        yield item("newer", "2026-09-01T00:00:00Z")


@pytest.fixture
def partial_company(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    (tmp_path / "companies").mkdir()
    write_company(synthetic_company("test_partial"))
    adapter = PartialAdapter()
    monkeypatch.setitem(adapters.REGISTRY, "canonical_jsonl", adapter)
    return adapter


def test_an_incomplete_fetch_loads_what_there_is_but_keeps_the_cursor(partial_company, monkeypatch):
    spy = SyncStateSpy(monkeypatch, CURSOR)
    seen: list[BuildEvent] = []

    report = pipeline.ingest("test_partial", on_event=seen.append)

    assert spy.written == [CURSOR]  # not 2026-09-01: the records still to come must pass it
    [result] = report.sources
    assert result.loaded == 1 and result.incomplete == partial_company.reason
    done = [e for e in seen if e.stage == "records" and e.status == "done"]
    assert done and partial_company.reason in done[0].message


def test_a_complete_fetch_moves_the_cursor(partial_company, monkeypatch):
    partial_company.reason = None
    spy = SyncStateSpy(monkeypatch, CURSOR)

    report = pipeline.ingest("test_partial")

    assert spy.written == [datetime(2026, 9, 1, tzinfo=UTC)]
    assert report.sources[0].incomplete is None


def test_a_full_ingest_of_an_incomplete_fetch_leaves_no_cursor(partial_company, monkeypatch):
    spy = SyncStateSpy(monkeypatch, CURSOR)
    pipeline.ingest("test_partial", full=True)
    assert spy.written == [None]  # nothing is known to be complete; the next ingest reloads all
