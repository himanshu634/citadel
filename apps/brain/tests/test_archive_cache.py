"""The archive cache: round trip, window exemption, and that a rebuild brings archived items
back (graph tests use a throwaway slug and a temp repo root)."""

from __future__ import annotations

import pytest
from brain import config, db, loader, pipeline, schema, tools
from brain.archive.cache import ArchiveEntry, archived_uids, read_entries, write_entry
from brain.canonical import Comment, Link, WorkItem
from brain.config import load_company
from brain.normalize import normalize
from brain.testing import needs_graph, synthetic_company, write_company

SLUG = "archtest_cache"
OLD = "2023-03-01T00:00:00Z"
REF = "github:acme/w#812"


def old_item(uid: str = "wi:old") -> WorkItem:
    return WorkItem(uid=uid, kind="issue", title="Old", state="closed", created_at=OLD,
                    closed_at=OLD, unresolved_refs=[REF])  # fmt: skip


def comments(uid: str = "wi:old") -> list[Comment]:
    return [
        Comment(uid=f"c{i}", work_item_uid=uid, author_login=f"user{i}", created_at=OLD, body="x")
        for i in range(2)
    ]


def entry(uid: str = "wi:old", key: str = "synthetic:x", records=None) -> ArchiveEntry:
    return ArchiveEntry(
        source_key=key,
        item_id=f"{key}#{uid}",
        uid=uid,
        ref=REF,
        archived_at="2026-10-17T00:00:00Z",
        request="why?",
        records=records if records is not None else [old_item(uid), *comments(uid)],
    )


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    (tmp_path / "companies").mkdir()
    return tmp_path


def test_entry_round_trip(root):
    e = entry()
    path = write_entry(SLUG, e)
    assert path.parent.name == "synthetic_x" and path.name == "synthetic_x_wi_old.jsonl"
    assert path.read_text().splitlines()[0].startswith('{"type": "meta"')
    (back,) = read_entries(SLUG)
    assert back == e
    assert archived_uids(SLUG) == {"wi:old"}
    assert pipeline.clear_archive(SLUG) == 1
    assert read_entries(SLUG) == []


def test_normalize_keeps_archived_children():
    cfg = synthetic_company("archtest_norm")
    records = [old_item(), *comments()]
    assert not [r for r in normalize(records, cfg) if isinstance(r, (WorkItem, Comment))]
    kept = list(normalize(records, cfg, keep=frozenset({"wi:old"})))
    assert len([r for r in kept if isinstance(r, WorkItem)]) == 1
    assert len([r for r in kept if isinstance(r, Comment)]) == 2


@pytest.fixture
def graph(root):
    cfg = synthetic_company(SLUG)
    write_company(cfg)
    db.delete_graph(SLUG)
    schema.apply_schema(SLUG)
    yield cfg
    db.delete_graph(SLUG)


@needs_graph
def test_ingest_loads_archive_without_cursor(graph):
    write_entry(SLUG, entry())
    pipeline.ingest(SLUG)
    pipeline.ingest(SLUG)
    got = tools.get_entity(SLUG, "wi:old")
    assert got.archived is True
    states = db.graph(SLUG).query("MATCH (s:SyncState) RETURN s.key").result_set
    assert not [r for r in states if str(r[0]).startswith("archive:")]


@needs_graph
def test_rebuild_restores_archive(graph):
    write_entry(SLUG, entry())
    pipeline.ingest(SLUG, full=True)
    db.delete_graph(SLUG)
    schema.apply_schema(SLUG)
    assert db.graph(SLUG).query("MATCH (w:WorkItem {uid:'wi:old'}) RETURN w").result_set == []
    pipeline.ingest(SLUG, full=True)
    got = tools.get_entity(SLUG, "wi:old")
    assert got.archived is True
    rows = (
        db.graph(SLUG)
        .query("MATCH (:Person)-[:COMMENTED_ON]->(:WorkItem {uid:'wi:old'}) RETURN count(*)")
        .result_set
    )
    assert rows[0][0] == 2


@needs_graph
def test_ingest_resolves_refs_to_archived(graph):
    other = WorkItem(uid="wi:new", kind="issue", title="New", state="open",
                     created_at="2026-10-01T00:00:00Z", unresolved_refs=[REF])  # fmt: skip
    loader.load(SLUG, [other])
    write_entry(SLUG, entry())
    pipeline.load_archive(SLUG, load_company(SLUG))
    new = tools.get_entity(SLUG, "wi:new")
    assert new.unresolved_refs == []
    assert [(n.rel, n.uid) for n in new.neighbours] == [("MENTIONS", "wi:old")]


def _blocks(a: str, b: str) -> Link:
    return Link(rel="BLOCKS", from_uid=a, from_label="WorkItem", to_uid=b, to_label="WorkItem")


def _count_blocks() -> int:
    return db.graph(SLUG).query("MATCH ()-[r:BLOCKS]->() RETURN count(r)").result_set[0][0]


@needs_graph
def test_archive_blocks_survive_linear_prune(graph):
    cfg = load_company(SLUG)
    e = entry("wi:a", key="linear:x", records=[old_item("wi:a"), old_item("wi:b"),
                                               _blocks("wi:a", "wi:b")])  # fmt: skip
    pipeline.load_entries(SLUG, cfg, [e])
    assert _count_blocks() == 1
    loader.load(SLUG, [], origin="linear:x")  # a Linear load that holds no BLOCKS edges
    assert _count_blocks() == 1


@needs_graph
def test_second_archive_keeps_first_blocks(graph):
    cfg = load_company(SLUG)
    a = entry("wi:a", key="linear:x", records=[old_item("wi:a"), old_item("wi:b"),
                                               _blocks("wi:a", "wi:b")])  # fmt: skip
    b = entry("wi:c", key="linear:x", records=[old_item("wi:c")])
    pipeline.load_entries(SLUG, cfg, [a])
    pipeline.load_entries(SLUG, cfg, [b])
    assert _count_blocks() == 1
