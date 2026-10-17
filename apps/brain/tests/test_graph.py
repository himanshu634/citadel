"""Loader and named tools against a real FalkorDB, on the synthetic company.

The synthetic data is designed with known answers (see examples/synthetic_company/generate.py).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from brain import db, loader, tools
from brain.canonical import Document, Link, WorkItem
from brain.embeddings import embed_pending
from brain.testing import FakeEmbedder, load_company, needs_graph, synthetic_company
from redis.exceptions import ResponseError

pytestmark = needs_graph


def stats(slug: str) -> dict[str, int]:
    return {f"{s.kind}:{s.type}": s.count for s in tools.graph_stats(slug)}


def test_ingesting_twice_gives_identical_counts(synthetic_graph):
    before = stats(synthetic_graph)
    load_company(synthetic_company(synthetic_graph))
    assert stats(synthetic_graph) == before
    assert before["node:Change"] == 25 and before["node:WorkItem"] == 15


def test_experts_rank_recent_humans_and_flag_owners(synthetic_graph):
    web = tools.experts_for_system(synthetic_graph, system="Web app")
    assert web[0].login == "erin" and not web[0].is_declared_owner
    assert web[0].declared_owners == ["identity"]
    assert {e.login for e in web if e.is_declared_owner} == {"alice", "carol"}

    infra = tools.experts_for_system(synthetic_graph, system="Infra")
    assert infra[0].login == "dave"  # ci-bot has more Infra commits but is a bot
    assert all(e.login != "ci-bot" for e in infra)
    assert tools.experts_for_system(synthetic_graph, system="No such system") == []


def test_owners_vs_experts_flags_only_web_app(synthetic_graph):
    gaps = tools.owners_vs_experts(synthetic_graph)
    assert [g.system for g in gaps] == ["Web app"]
    assert gaps[0].top_contributors[0].login == "erin" and gaps[0].members_known


def test_work_history_impact_and_path(synthetic_graph):
    auth = tools.work_history(synthetic_graph, system="Auth")
    assert [w.number for w in auth] == [10, 2, 1]
    assert [c.number for c in auth[-1].closes] == [11]

    impact = tools.impact_of(synthetic_graph, system="Billing")
    assert impact[0].system == "Web app" and impact[0].co_changes == 3

    paths = tools.path_between(synthetic_graph, "person:erin", "system:Auth")
    assert paths and paths[0].nodes[0].uid == "person:erin"
    assert paths[0].nodes[-1].uid == "system:Auth" and paths[0].length == len(paths[0].rels)


def test_text_search_over_work_items_and_documents(synthetic_graph):
    items = tools.related_work_items(synthetic_graph, text="invoice duplicate batch")
    numbers = [w.number for w in items]
    assert 4 in numbers and 14 in numbers
    assert "Billing" in next(w for w in items if w.number == 4).systems

    docs = tools.related_documents(synthetic_graph, text="managed postgres")
    assert docs[0].path == "docs/adr/001-managed-postgres.md" and "Infra" in docs[0].systems
    assert tools.related_work_items(synthetic_graph, text="a ? !") == []  # no usable words


def test_profile_entity_and_systems(synthetic_graph):
    erin = tools.person_profile(synthetic_graph, login="Erin")  # case-insensitive
    assert erin.teams == ["payments"] and erin.prs_authored == 3
    assert erin.systems[0].system == "Web app"
    bot = tools.person_profile(synthetic_graph, login="ci-bot")  # no PRs, no reviews
    assert bot.prs_authored == 0 and bot.recent_prs == [] and bot.recent_reviews == []

    issue = tools.get_entity(synthetic_graph, uid="synthetic:issue:14")
    assert issue.title == "Invoice emails sometimes sent twice"
    assert any(
        n.rel == "AUTHORED" and n.direction == "in" and n.uid == "person:erin"
        for n in issue.neighbours
    )
    assert tools.get_entity(synthetic_graph, uid="nope") is None

    assert {s.system for s in tools.list_systems(synthetic_graph)} == {
        "Auth",
        "Billing",
        "Web app",
        "Infra",
    }


def test_recent_work_items_newest_first(synthetic_graph):
    rows = tools.call(synthetic_graph, "recent_work_items", limit=5)
    assert [r.uid for r in rows] == [
        "synthetic:issue:14",
        "synthetic:pr:10",
        "synthetic:pr:9",
        "synthetic:slack:thread:eng-2026-07-15",
        "synthetic:pr:8",
    ]
    assert rows[0].last_at.startswith("2026-09-10")
    assert rows[1].last_at == "2026-09-05T12:00:00Z"  # a merged PR counts from its merge
    assert [r.last_at for r in rows] == sorted((r.last_at for r in rows), reverse=True)
    assert (rows[0].author, rows[0].number, rows[0].state) == ("erin", 14, "open")
    assert rows[1].systems == ["Auth", "Web app"] and rows[0].systems == []


def test_people_activity_excludes_bots(synthetic_graph):
    rows = tools.call(synthetic_graph, "people_activity")
    by_login = {r.login: r for r in rows}
    assert "ci-bot" not in by_login and {"alice", "erin"} <= by_login.keys()
    erin = by_login["erin"]
    assert (erin.prs, erin.reviews, erin.teams) == (3, 2, ["payments"])
    assert (erin.person_uid, erin.display_name) == ("person:erin", "Erin Novak")
    assert by_login["alice"].reviews == 3
    assert by_login["dave"].teams == []
    assert [r.login for r in tools.call(synthetic_graph, "people_activity", limit=2)] == [
        "alice",
        "erin",
    ]


def test_unknown_tool_and_bad_params(synthetic_graph):
    with pytest.raises(KeyError):
        tools.call(synthetic_graph, "drop_everything")
    with pytest.raises(ValueError):
        tools.call(synthetic_graph, "impact_of")  # system is required


def test_fulltext_query_cannot_inject_syntax():
    assert tools.fulltext_query("vector-index @crash* (dims)") == "vector|index|crash|dims"


def test_two_companies_stay_isolated(synthetic_graph, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "people.jsonl").write_text(json.dumps({"login": "zed"}) + "\n")
    (other / "changes.jsonl").write_text(
        json.dumps(
            {
                "uid": "other:commit:1",
                "sha": "1",
                "date": "2026-05-01T00:00:00Z",
                "author_login": "zed",
                "subject": "feat: x",
                "files": ["web/a.ts"],
            }
        )
        + "\n"
    )
    slug = "test_other"
    db.delete_graph(slug)
    try:
        load_company(synthetic_company(slug, other))
        assert [e.login for e in tools.experts_for_system(slug, system="Web app")] == ["zed"]
        assert "zed" not in {
            e.login for e in tools.experts_for_system(synthetic_graph, system="Web app")
        }
        assert stats(slug)["node:Change"] == 1 and stats(synthetic_graph)["node:Change"] == 25
    finally:
        db.delete_graph(slug)
    assert stats(synthetic_graph)["node:Change"] == 25  # deleting one graph leaves the other


def test_read_on_a_missing_graph_has_no_rows():
    """A rebuild may delete the graph between a caller's graph_exists check and its read."""
    slug = "test_never_created"
    db.delete_graph(slug)
    assert db.run(slug, "tools/recent_work_items", {"limit": 3}, read_only=True) == []
    assert not db.graph_exists(slug)  # the read did not create it


def test_a_broken_read_on_an_existing_graph_still_raises(synthetic_graph, monkeypatch):
    monkeypatch.setattr(db.queries, "get", lambda name: SimpleNamespace(body="NOT CYPHER"))
    with pytest.raises(ResponseError):
        db.run(synthetic_graph, "tools/anything", read_only=True)


def test_bodies_and_documents_become_chunks(synthetic_graph):
    chunks = "MATCH (c:Chunk)-[:FROM]->({uid: $uid}) RETURN c.uid ORDER BY c.uid"

    def chunks_of(uid: str) -> list[str]:
        return [r[0] for r in db.run_text(synthetic_graph, chunks, {"uid": uid}).result_set]

    issue_chunks = ["chunk:synthetic:comment:7", "chunk:synthetic:issue:14:body"]
    assert chunks_of("synthetic:issue:14") == issue_chunks
    doc_uid = "synthetic:doc:docs/billing-runbook.md"
    assert chunks_of(doc_uid) == [f"chunk:{doc_uid}:0"]
    # get_entity lists comment chunks, not the body and document chunks (their text is `body`)
    issue = tools.get_entity(synthetic_graph, uid="synthetic:issue:14")
    listed = [n.uid for n in issue.neighbours if n.label == "Chunk"]
    assert listed == ["chunk:synthetic:comment:7"]
    doc = tools.get_entity(synthetic_graph, uid=doc_uid)
    assert not any(n.label == "Chunk" for n in doc.neighbours)
    node_rows = db.run(
        synthetic_graph, "graph/nodes", {"labels": ["WorkItem", "Document"]}, read_only=True
    )
    rows = {r["uid"]: r for r in node_rows}
    assert rows["synthetic:issue:14"]["comments"] == 1  # its body chunk is not a comment
    assert rows["synthetic:pr:3"]["comments"] == 2


def test_chunks_carry_a_text_hash_of_their_text(synthetic_graph):
    rows = db.run_text(
        synthetic_graph,
        "MATCH (c:Chunk) RETURN c.kind AS kind, count(c) AS n, count(c.text_hash) AS hashed",
    )
    got = {kind: (n, hashed) for kind, n, hashed in rows.result_set}
    assert set(got) == {"comment", "work_item", "document"}
    assert all(n == hashed for n, hashed in got.values())


def test_shrunk_document_leaves_no_stale_chunks():
    slug = "test_doc_shrink"
    db.delete_graph(slug)
    try:
        long = "\n\n".join(f"para{i} " * 200 for i in range(3))  # several chunks at 1200 chars

        def doc(body):
            return Document(uid="t:doc:a.md", source="t", path="a.md", title="A", body=body)

        chunks = "MATCH (c:Chunk)-[:FROM]->(:Document) RETURN c.uid AS uid"
        loader.load(slug, [doc(long)])
        assert len(db.run_text(slug, chunks).result_set) > 1  # it is cut into several
        loader.load(slug, [doc("one short paragraph")])
        rows = db.run_text(slug, chunks)
        assert [r[0] for r in rows.result_set] == ["chunk:t:doc:a.md:0"]
    finally:
        db.delete_graph(slug)


BODY_CHUNKS = (
    "MATCH (c:Chunk {kind: 'work_item'})-[:FROM]->(w:WorkItem) "
    "RETURN c.uid, c.text, c.company, c.created_at, c.ts, c.source, c.url, w.uid ORDER BY c.uid"
)


def backfill_items() -> list[WorkItem]:
    """A body, a body of only line breaks (it reads as no body), and no body at all."""

    def item(n: int, title: str, body: str) -> WorkItem:
        return WorkItem(
            uid=f"t:pr:{n}", source="t", url=f"https://example.com/pull/{n}", kind="pull_request",
            number=n, title=title, body=body, state="open", created_at=f"2026-09-0{n}T12:00:00Z",
        )  # fmt: skip

    return [
        item(1, "Retry failed charges", "Adds an idempotency key.\n\nSee #4."),
        item(2, "Bump lockfile", "\r\n"),
        item(3, "Rename the queue", ""),
    ]


def test_backfill_writes_missing_body_chunks_as_a_load_would():
    """An upgraded graph has work items but no body chunks, and an incremental ingest skips the
    old items; the backfill must write exactly what a load writes, then nothing."""
    slug = "test_body_backfill"
    db.delete_graph(slug)
    try:
        loader.load(slug, backfill_items())
        loaded = db.run_text(slug, BODY_CHUNKS).result_set
        assert len(loaded) == 3
        db.run_text(slug, "MATCH (c:Chunk {kind: 'work_item'}) DETACH DELETE c")
        assert loader.backfill_chunks(slug) == 3
        assert db.run_text(slug, BODY_CHUNKS).result_set == loaded
        assert loader.backfill_chunks(slug) == 0
    finally:
        db.delete_graph(slug)


def test_a_backfilled_body_chunk_is_not_embedded_again_by_a_later_load():
    """The backfill cannot hash in Cypher; the embed stage fills the hash from the text, and a
    later load of the same item writes the same text, so nothing is pending."""
    slug = "test_backfill_embed"
    db.delete_graph(slug)
    try:
        loader.load(slug, backfill_items())
        db.run_text(slug, "MATCH (c:Chunk {kind: 'work_item'}) DETACH DELETE c")
        loader.backfill_chunks(slug)
        assert embed_pending(slug, FakeEmbedder()).embedded == 3
        hashed = "MATCH (c:Chunk) RETURN count(c.text_hash)"
        assert db.run_text(slug, hashed).result_set[0][0] == 3  # filled when embedded
        loader.load(slug, backfill_items())
        assert embed_pending(slug, FakeEmbedder()).embedded == 0
    finally:
        db.delete_graph(slug)


def test_a_long_document_still_shows_its_links():
    """Document chunks would sort first (FROM before MENTIONS) and fill a small limit."""
    slug = "test_entity_doc"
    db.delete_graph(slug)
    try:
        body = "\n\n".join(f"para{i} " * 200 for i in range(3))  # several chunks at 1200 chars
        doc = Document(uid="t:doc:a.md", source="t", path="a.md", title="A", body=body)
        pr = backfill_items()[0]
        link = Link(rel="MENTIONS", from_uid=doc.uid, from_label="Document", to_uid=pr.uid,
                    to_label="WorkItem", source="t")  # fmt: skip
        loader.load(slug, [doc, pr, link])
        entity = tools.get_entity(slug, uid=doc.uid, limit=1)
        assert [(n.rel, n.uid) for n in entity.neighbours] == [("MENTIONS", pr.uid)]
        assert entity.neighbour_count == 1  # counts what it lists
    finally:
        db.delete_graph(slug)


def test_a_chunk_uid_opens_its_passage_and_its_source(synthetic_graph):
    """The prompt sends the agent from a semantic_search hit's chunk_uid to get_entity."""
    chunk = tools.get_entity(synthetic_graph, uid="chunk:synthetic:comment:3")
    assert chunk is not None and chunk.label == "Chunk" and chunk.kind == "comment"
    assert "Rounding is off by a cent" in chunk.body
    links = {(n.rel, n.direction, n.uid) for n in chunk.neighbours}
    assert ("FROM", "out", "synthetic:pr:3") in links
