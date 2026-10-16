"""Incremental-ingest cursor rules (pure, no database)."""

from datetime import UTC, datetime

from brain.canonical import Change, Document, Person, WorkItem
from brain.pipeline import next_cursor, select_new

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
