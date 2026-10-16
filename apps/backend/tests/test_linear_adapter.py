"""Linear transform: raw cache (tests/fixtures/linear/synthetic-co) -> canonical records."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from brain import db, loader, schema
from brain.adapters import REGISTRY, SourceUnavailable
from brain.adapters.linear import LinearAdapter, LinearSource
from brain.adapters.linear.transform import PRIORITY_MAP, STATUS_MAP, issue_uid, records
from brain.canonical import Comment, Link, Person, Team, WorkItem, url_ref
from brain.config import CompanyConfig
from conftest import needs_graph

FIXTURE = Path(__file__).parent / "fixtures" / "linear" / "synthetic-co"


def company() -> CompanyConfig:
    return CompanyConfig.model_validate(
        {
            "slug": "lin_test",
            "name": "Linear test",
            "data_permission": "synthetic",
            "window": {"since": "2026-01-01"},
            "sources": [{"type": "linear", "workspace": "synthetic-co"}],
        }
    )


SOURCE = LinearSource.model_validate({"type": "linear", "workspace": "synthetic-co"})


@pytest.fixture(scope="module")
def recs() -> list:
    return list(records(company(), SOURCE, FIXTURE))


def tickets(recs) -> dict[str, WorkItem]:
    return {r.key: r for r in recs if isinstance(r, WorkItem)}


def links(recs, rel: str) -> list[Link]:
    return [r for r in recs if isinstance(r, Link) and r.rel == rel]


def test_ticket_fields(recs):
    t = tickets(recs)["IDN-1"]
    assert t.uid == issue_uid("i-1") == "linear:issue:i-1"
    assert (t.kind, t.source, t.number) == ("ticket", "linear", 1)
    assert t.title == "Rotate signing keys"
    assert t.body == "Keys older than 90 days must be rotated."
    assert (t.state, t.status_category, t.priority) == ("In Progress", "in_progress", "high")
    assert t.due_date == date(2026, 11, 6)
    assert t.created_at == datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    assert t.updated_at == datetime(2026, 10, 12, 10, 30, tzinfo=UTC)
    assert t.closed_at is None
    assert t.author_login == "bob"
    assert t.assignees == ["alice"]
    assert t.labels == ["security", "ops"]
    assert t.container == "IDN"
    assert t.url == "https://linear.app/synthetic-co/issue/IDN-1"


def test_closed_at_from_completed_or_canceled(recs):
    by_key = tickets(recs)
    assert by_key["PAY-2"].closed_at == datetime(2026, 10, 8, 9, 0, tzinfo=UTC)
    assert by_key["PAY-2"].status_category == "done"
    assert by_key["IDN-3"].closed_at == datetime(2026, 10, 9, 9, 0, tzinfo=UTC)
    assert by_key["IDN-3"].status_category == "canceled"


def test_status_and_priority_maps(recs):
    assert STATUS_MAP["triage"] == "backlog"
    assert PRIORITY_MAP[0] is None
    by_key = tickets(recs)
    assert by_key["IDN-2"].status_category == "backlog"  # triage
    assert by_key["PAY-1"].status_category == "todo"  # weird_new_type falls back to todo
    assert by_key["PAY-1"].state == "Review"  # the raw state name is kept
    assert by_key["IDN-2"].priority is None  # priority 0
    assert by_key["PAY-1"].priority == "low"
    assert by_key["PAY-2"].priority == "urgent"
    assert by_key["IDN-4"].priority == "medium"


def test_unassigned_is_empty_list(recs):
    assert tickets(recs)["IDN-2"].assignees == []


def test_missing_creator_is_none_author(recs):
    assert tickets(recs)["IDN-4"].author_login is None


def test_blocks_from_both_directions_once(recs):
    found = links(recs, "BLOCKS")
    pairs = [(link.from_uid, link.to_uid) for link in found]
    assert sorted(pairs) == sorted(
        [
            ("linear:issue:i-1", "linear:issue:i-2"),  # on both sides, emitted once
            ("linear:issue:i-6", "linear:issue:i-1"),  # relations only
            ("linear:issue:i-5", "linear:issue:i-3"),  # inverseRelations only
            ("linear:issue:i-3", "linear:issue:i-9"),  # blocker outside the cache
        ]
    )
    assert all(link.source == "linear" for link in found)


def test_duplicate_relation_ignored(recs):
    touching_i4 = [
        r for r in recs if isinstance(r, Link) and "linear:issue:i-4" in (r.from_uid, r.to_uid)
    ]
    assert touching_i4 == []


def test_related_relation_is_a_mention(recs):
    mentions = {(m.from_uid, m.to_uid) for m in links(recs, "MENTIONS")}
    assert ("linear:issue:i-1", "linear:issue:i-3") in mentions
    assert ("linear:issue:i-3", "linear:issue:i-1") not in mentions  # only `relations` is read


def test_attachment_is_url_mention(recs):
    pr_url = "https://github.com/synthetic-co/app/pull/12"
    found = [m for m in links(recs, "MENTIONS") if m.to_uid == url_ref(pr_url)]
    assert [(m.from_uid, m.from_label, m.to_label) for m in found] == [
        ("linear:issue:i-1", "WorkItem", "WorkItem")
    ]


def test_comment_without_user_skipped(recs):
    comments = [r for r in recs if isinstance(r, Comment)]
    assert [c.uid for c in comments] == ["linear:comment:c-1"]
    assert comments[0].work_item_uid == "linear:issue:i-1"
    assert comments[0].author_login == "alice"
    assert comments[0].body == "Started on the rotation job."


def test_team_move_keeps_one_node(recs):
    moved = [r for r in recs if isinstance(r, WorkItem) and r.uid == "linear:issue:i-7"]
    assert len(moved) == 1
    assert (moved[0].key, moved[0].container) == ("PAY-4", "PAY")
    assert moved[0].assignees == ["dave"]
    assert "IDN-7" not in tickets(recs)


def test_members_and_teams(recs):
    people = {r.login: r for r in recs if isinstance(r, Person)}
    assert set(people) == {"alice", "bob", "carol", "dave"}  # the blank displayName is skipped
    assert people["alice"].display_name == "Alice Anders"
    assert {r.name for r in recs if isinstance(r, Team)} == {"Identity", "Payments"}
    member_of = {(m.from_uid, m.to_uid) for m in links(recs, "MEMBER_OF")}
    assert member_of == {
        ("person:alice", "team:identity"),
        ("person:bob", "team:identity"),  # carol is inactive: a person, but no membership
        ("person:dave", "team:payments"),
        ("person:bob", "team:payments"),
    }


def test_no_email_in_records(recs):
    for rec in recs:
        for name, value in rec.model_dump().items():
            strings = value if isinstance(value, list) else [value]
            assert not any(isinstance(s, str) and "@" in s for s in strings), (rec.uid, name)


def test_no_cache_raises_source_unavailable(tmp_path):
    with pytest.raises(SourceUnavailable):
        list(records(company(), SOURCE, tmp_path / "nothing"))


def test_registered_and_yaml_validates():
    adapter = REGISTRY["linear"]
    assert isinstance(adapter, LinearAdapter) and adapter.name == "linear"
    cfg = company()
    source = cfg.sources[0]
    assert isinstance(source, LinearSource) and source.teams == []
    assert adapter.key(source) == "linear:synthetic-co"
    assert adapter.cache_for(source, Path("/c")) == Path("/c/synthetic-co")
    assert list(adapter.records(cfg, source, FIXTURE.parent))  # cache_for appends the workspace


def test_blocker_outside_cache_is_a_dangling_link(recs):
    dangling = [lk for lk in links(recs, "BLOCKS") if lk.to_uid == "linear:issue:i-9"]
    assert len(dangling) == 1
    assert "linear:issue:i-9" not in {r.uid for r in recs if isinstance(r, WorkItem)}


@needs_graph
def test_dangling_blocker_is_dropped_by_the_loader(recs):
    slug = "test_linear_dangling"
    db.delete_graph(slug)
    try:
        schema.apply_schema(slug)
        report = loader.load(slug, recs, origin="linear:synthetic-co")
        assert report.dropped["load/link_blocks"] == 1  # i-3 -> i-9
        assert report.written["load/link_blocks"] == 3
    finally:
        db.delete_graph(slug)
