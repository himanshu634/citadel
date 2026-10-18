"""Linear transform: raw cache (tests/fixtures/linear/synthetic-co) -> canonical records."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from brain import db, loader, schema
from brain.adapters import REGISTRY, SourceUnavailable
from brain.adapters.linear import LinearAdapter, LinearSource
from brain.adapters.linear.transform import PRIORITY_MAP, STATUS_MAP, issue_uid, records
from brain.canonical import Comment, Link, Person, Team, WorkItem, url_ref
from brain.config import CompanyConfig
from brain.testing import needs_graph

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
NEWER_RUN = "20261017T000000"  # a third run, added on top of a copy of the fixture


def fixture_copy(tmp_path: Path) -> Path:
    cache = tmp_path / "synthetic-co"
    shutil.copytree(FIXTURE, cache)
    return cache


def add_run(cache: Path, run_id: str, nodes: list[dict]) -> None:
    """Add a completed run holding `nodes` (one page), as fetch would leave it."""
    folder = cache / "issues"
    (folder / f"{run_id}_0000.json").write_text(json.dumps(nodes))
    state = json.loads((folder / "state.json").read_text())
    state["completed_runs"].append(run_id)
    (folder / "state.json").write_text(json.dumps(state))


def newest_nodes(cache: Path) -> list[dict]:
    """The issue nodes of the fixture's newest run."""
    return json.loads((cache / "issues" / "20261016T120000_0000.json").read_text())


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


def no_completed_run(cache: Path) -> None:
    """A run that started but never completed: its page is on disk, state.json lists nothing."""
    folder = cache / "issues"
    for page in folder.glob("*_*.json"):
        page.unlink()
    (folder / "20261017T000000_0000.json").write_text("[]")
    (folder / "state.json").write_text(
        json.dumps({"complete_until": None, "completed_runs": [], "run": "20261017T000000"})
    )


@pytest.mark.parametrize(
    "leave",
    [lambda cache: shutil.rmtree(cache / "issues"), no_completed_run],
    ids=["issues folder cleared", "run not completed"],
)
def test_no_completed_issues_run_is_unavailable(tmp_path, leave):
    """No completed issues run (the folder was cleared for a team change and the fetch after
    it failed, or a first run never completed): records raises, so ingest skips the source.
    Loading the teams alone would make the loader prune every Linear BLOCKS edge."""
    cache = fixture_copy(tmp_path)
    leave(cache)
    with pytest.raises(SourceUnavailable, match="no completed"):
        list(records(company(), SOURCE, cache))


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


def test_records_skip_issues_outside_configured_teams():
    only_idn = LinearSource.model_validate(
        {"type": "linear", "workspace": "synthetic-co", "teams": ["IDN"]}
    )
    found = tickets(list(records(company(), only_idn, FIXTURE)))
    assert {t.container for t in found.values()} == {"IDN"}
    assert set(found) == {"IDN-1", "IDN-2", "IDN-3", "IDN-4"}  # i-7 is PAY-4 now: skipped


def test_issue_missing_from_newest_run_becomes_removed(tmp_path):
    """i-1 (open, assigned, blocking) is archived in Linear: the next run no longer returns it."""
    cache = fixture_copy(tmp_path)
    add_run(cache, NEWER_RUN, [n for n in newest_nodes(cache) if n["id"] != "i-1"])
    recs = list(records(company(), SOURCE, cache))

    removed = tickets(recs)["IDN-1"]
    assert (removed.status_category, removed.state) == ("canceled", "Removed from Linear")
    assert removed.assignees == []
    assert removed.updated_at == removed.closed_at == datetime(2026, 10, 17, tzinfo=UTC)
    assert (removed.title, removed.container) == ("Rotate signing keys", "IDN")
    uid = issue_uid("i-1")
    assert [r for r in recs if isinstance(r, Link) and uid in (r.from_uid, r.to_uid)] == []
    assert [r for r in recs if isinstance(r, Comment) and r.work_item_uid == uid] == []
    # still-open issues in the newest run and closed issues are left as they were
    assert tickets(recs)["IDN-2"].status_category == "backlog"
    assert tickets(recs)["PAY-2"].state == "Done"
    assert tickets(recs)["PAY-4"].status_category == "in_progress"  # the team move survives


def test_display_name_with_at_is_skipped(tmp_path):
    """A Linear displayName can be an email address; it is never stored and never aborts."""
    cache = fixture_copy(tmp_path)
    teams = json.loads((cache / "teams.json").read_text())
    teams[0]["members"]["nodes"].append(
        {"id": "u-9", "displayName": "erin@example.com", "name": "Erin", "active": True}
    )
    (cache / "teams.json").write_text(json.dumps(teams))
    nodes = newest_nodes(cache)
    for node in nodes:
        if node["id"] == "i-1":
            node["assignee"] = node["creator"] = {"displayName": "erin@example.com"}
            node["comments"]["nodes"][0]["user"] = {"displayName": "erin@example.com"}
    add_run(cache, NEWER_RUN, nodes)

    recs = list(records(company(), SOURCE, cache))
    t = tickets(recs)["IDN-1"]
    assert (t.assignees, t.author_login) == ([], None)
    assert "erin@example.com" not in {r.login for r in recs if isinstance(r, Person)}
    assert not [r for r in recs if isinstance(r, Comment) and r.work_item_uid == t.uid]


@needs_graph
def test_removed_ticket_loses_assignee_and_blocks(tmp_path):
    slug = "test_linear_removed"
    origin = "linear:synthetic-co"
    uid = issue_uid("i-1")
    cache = fixture_copy(tmp_path)
    db.delete_graph(slug)
    try:
        schema.apply_schema(slug)
        loader.load(slug, list(records(company(), SOURCE, cache)), origin=origin)
        before = db.rows(
            db.run_text(
                slug,
                "MATCH (w:WorkItem {uid: $uid}) RETURN w.status_category AS cat, "
                "size([(w)<-[:ASSIGNED_TO]-(p) | p]) AS assigned, "
                "size([(w)-[:BLOCKS]->(x) | x]) AS blocks",
                {"uid": uid},
            )
        )
        assert before == [{"cat": "in_progress", "assigned": 1, "blocks": 1}]

        add_run(cache, NEWER_RUN, [n for n in newest_nodes(cache) if n["id"] != "i-1"])
        loader.load(slug, list(records(company(), SOURCE, cache)), origin=origin)
        after = db.rows(
            db.run_text(
                slug,
                "MATCH (w:WorkItem {uid: $uid}) RETURN w.status_category AS cat, "
                "size([(w)<-[:ASSIGNED_TO]-(p) | p]) AS assigned, "
                "size([(w)-[:BLOCKS]-(x) | x]) AS blocks",
                {"uid": uid},
            )
        )
        assert after == [{"cat": "canceled", "assigned": 0, "blocks": 0}]
    finally:
        db.delete_graph(slug)


def test_relation_to_uncached_issue_is_unresolved_ref(recs):
    items = tickets(recs)
    blocker = next(r for r in recs if isinstance(r, WorkItem) and r.uid == "linear:issue:i-3")
    assert blocker.unresolved_refs == ["linear:issue:i-9"]
    assert all(w.unresolved_refs == [] for w in items.values() if w.uid != "linear:issue:i-3")


def test_incomplete_while_the_issue_run_is_unfinished(tmp_path):
    cache = fixture_copy(tmp_path)
    adapter = REGISTRY["linear"]
    assert adapter.incomplete(company(), SOURCE, tmp_path) is None

    state_file = cache / "issues" / "state.json"
    state = json.loads(state_file.read_text())
    state["run"] = {"id": NEWER_RUN, "lower": "x", "cursor": "c", "page": 1}
    state_file.write_text(json.dumps(state))
    reason = adapter.incomplete(company(), SOURCE, tmp_path)
    assert reason and NEWER_RUN in reason

    shutil.rmtree(cache / "issues")  # never fetched
    assert adapter.incomplete(company(), SOURCE, tmp_path) == "issues: not fetched yet"
