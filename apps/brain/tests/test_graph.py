"""Loader and named tools against a real FalkorDB, on the synthetic company.

The synthetic data is designed with known answers (see examples/synthetic_company/generate.py).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from brain import db, keeper, loader, schema, tools
from brain.canonical import Document, Link, Person, System, WorkItem
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


def test_collaborators_rank_pairs_by_reviews_of_each_other(synthetic_graph):
    rows = tools.collaborators(synthetic_graph)
    pairs = [[p.login for p in r.people] for r in rows]
    # alice+carol and bob+erin each reviewed 3 of the other's PRs; ties go by login
    assert pairs[:3] == [["alice", "carol"], ["bob", "erin"], ["alice", "dave"]]
    top = rows[0]
    assert (top.reviews, top.a_reviewed_b, top.b_reviewed_a) == (3, 1, 2)
    assert [e.uid for e in top.examples] == ["synthetic:pr:10", "synthetic:pr:2", "synthetic:pr:1"]
    assert top.people[1].person_uid == "person:carol" and top.shared_threads == 0
    assert all("ci-bot" not in p for p in pairs)

    erin = tools.collaborators(synthetic_graph, login="Erin")  # that person first
    assert [[p.login for p in r.people] for r in erin] == [
        ["erin", "bob"],
        ["erin", "alice"],
        ["erin", "carol"],
    ]
    assert (erin[0].a_reviewed_b, erin[0].b_reviewed_a) == (2, 1)
    assert tools.collaborators(synthetic_graph, login="nobody") == []


def test_issues_by_system_counts_linked_issues(synthetic_graph):
    rows = tools.issues_by_system(synthetic_graph)
    assert [(r.system, r.issues) for r in rows] == [("Web app", 3), ("Billing", 2), ("Auth", 1)]
    web = rows[0]
    assert (web.open, web.closed, web.mentioned, web.fixed_in) == (0, 3, 0, 3)
    assert [e.number for e in web.examples] == [13, 12, 11]
    assert web.system_uid == "system:Web app"
    assert tools.issues_by_system(synthetic_graph, state="open") == []


def test_issues_by_system_ranks_mentions_and_leaves_out_bot_issues():
    slug = "test_issue_counts"
    db.delete_graph(slug)
    try:

        def issue(n: int, state: str = "open", author: str = "erin", **kw) -> WorkItem:
            kw.setdefault("kind", "issue")
            return WorkItem(uid=f"t:issue:{n}", source="t", number=n,
                            title=f"bug {n}", state=state, author_login=author,
                            created_at=f"2026-05-0{n}T00:00:00Z", **kw)  # fmt: skip

        def mentions(n: int, system: str) -> Link:
            return Link(rel="MENTIONS", from_uid=f"t:issue:{n}", from_label="WorkItem",
                        to_uid=f"system:{system}", to_label="System", source="t")  # fmt: skip

        records = [
            Person(login="erin"), Person(login="ci-bot", is_bot=True),
            System(name="Auth"), System(name="Web app"),
            issue(1), issue(2, "closed"), issue(3), issue(4, author="ci-bot"),
            # tickets: open or closed by status_category, not by the state's name
            issue(5, "In Progress", kind="ticket", status_category="in_progress"),
            issue(6, "Done", kind="ticket", status_category="done"),
            mentions(1, "Auth"), mentions(2, "Auth"), mentions(5, "Auth"), mentions(6, "Auth"),
            mentions(3, "Web app"), mentions(4, "Web app"), mentions(1, "Web app"),
        ]  # fmt: skip
        loader.load(slug, records)
        rows = tools.issues_by_system(slug)
        assert [(r.system, r.mentioned, r.open, r.closed) for r in rows] == [
            ("Auth", 4, 2, 2),
            ("Web app", 2, 2, 0),  # issue 4 is the bot's
        ]
        assert [r.system for r in tools.issues_by_system(slug, state="closed")] == ["Auth"]
    finally:
        db.delete_graph(slug)


def test_central_nodes_rank_by_pagerank(synthetic_graph):
    systems = tools.central_nodes(synthetic_graph)
    # Infra has the most changes, docs and owners pointing at it
    assert [r.uid for r in systems] == [
        "system:Infra",
        "system:Billing",
        "system:Web app",
        "system:Auth",
    ]
    assert all(r.label == "System" and r.kind == "system" for r in systems)
    assert [r.score for r in systems] == sorted((r.score for r in systems), reverse=True)

    items = tools.central_nodes(synthetic_graph, label="WorkItem", limit=2)
    assert [(r.uid, r.kind, r.number) for r in items] == [
        ("synthetic:issue:11", "issue", 11),
        ("synthetic:issue:12", "issue", 12),
    ]
    assert items[0].url and items[0].name == "Session table causes DB load spikes"

    docs = tools.central_nodes(synthetic_graph, label="Document")
    assert len(docs) == 3 and all(r.kind == "document" and r.url for r in docs)
    with pytest.raises(ValueError):
        tools.call(synthetic_graph, "central_nodes", label="Person")  # flat for people


def test_bottlenecks_on_the_synthetic_tickets(ticket_graph):
    rows = tools.bottlenecks(ticket_graph)
    # PAY-3 -MENTIONS-> pr:9 -MENTIONS-> pr:3 -CLOSES-> issue:12: pr:9 and pr:3 each sit on two
    # shortest paths; pr:1 (pr:6 -> pr:1 -> issue:11) and PAY-2 (PAY-3 -> PAY-2 -> IDN-2) on one
    assert [(r.uid, r.score) for r in rows] == [
        ("synthetic:pr:3", 16.0),  # 8 seeded runs x 2 paths; ties by uid
        ("synthetic:pr:9", 16.0),
        ("synthetic:pr:1", 8.0),
        ("synthetic:ticket:PAY-2", 8.0),
    ]
    assert rows[3].key == "PAY-2" and rows[3].url
    assert [r.uid for r in tools.bottlenecks(ticket_graph, open_only=True)] == [
        "synthetic:pr:9",
        "synthetic:ticket:PAY-2",  # In Progress: open by status_category
    ]
    assert len(tools.bottlenecks(ticket_graph, limit=1)) == 1


def test_bottlenecks_leave_out_bots_and_closed_work():
    slug = "test_bottlenecks"
    db.delete_graph(slug)
    try:
        assert tools.bottlenecks(slug) == []  # no graph at all

        def item(n: int, kind: str = "issue", author: str = "erin", **kw) -> WorkItem:
            kw.setdefault("state", "open")
            return WorkItem(uid=f"t:{kind}:{n}", source="t", kind=kind, number=n,
                            title=f"{kind} {n}", author_login=author,
                            created_at=f"2026-05-0{n}T00:00:00Z", **kw)  # fmt: skip

        def link(rel: str, a: str, b: str) -> Link:
            return Link(rel=rel, from_uid=a, from_label="WorkItem", to_uid=b,
                        to_label="WorkItem", source="t")  # fmt: skip

        loader.load(slug, [Person(login="erin"), System(name="Auth")])
        assert tools.bottlenecks(slug) == []  # no work items, no links: no rows, no error

        records = [
            Person(login="erin"), Person(login="dep-bot", is_bot=True),
            # an open ticket in the middle of a BLOCKS chain
            item(1, "ticket", status_category="todo", state="Todo"),
            item(2, "ticket", status_category="in_progress", state="In Progress"),
            item(3, "ticket", status_category="todo", state="Todo"),
            link("BLOCKS", "t:ticket:1", "t:ticket:2"), link("BLOCKS", "t:ticket:2", "t:ticket:3"),
            # a closed issue in the middle of a MENTIONS chain
            item(4), item(5, state="closed"), item(6),
            link("MENTIONS", "t:issue:4", "t:issue:5"), link("MENTIONS", "t:issue:5", "t:issue:6"),
            # a bot's PR in the middle of a CLOSES chain
            item(7, "pull_request", author="dep-bot"), item(8),
            link("MENTIONS", "t:issue:6", "t:pull_request:7"),
            link("CLOSES", "t:pull_request:7", "t:issue:8"),
        ]  # fmt: skip
        loader.load(slug, records)
        rows = tools.bottlenecks(slug)
        assert "t:pull_request:7" not in {r.uid for r in rows}
        assert {r.uid for r in rows} == {"t:issue:5", "t:issue:6", "t:ticket:2"}
        assert all(r.score > 0 for r in rows)
        open_rows = tools.bottlenecks(slug, open_only=True)
        assert {r.uid for r in open_rows} == {"t:issue:6", "t:ticket:2"}
    finally:
        db.delete_graph(slug)


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


# Every lookup of a node by uid, with the params each query takes. Each must be served by the
# Node.uid range index: a label-less `MATCH (n {uid: $uid})` is an All Node Scan, which on a
# real company graph walks every chunk of text for each lookup.
UID_LOOKUPS = {
    "tools/get_entity": {"uid": "synthetic:pr:4", "limit": 25},
    "tools/path_between": {
        "from_uid": "person:erin",
        "to_uid": "system:Auth",
        "max_len": 6,
        "paths": 3,
    },  # fmt: skip
    "keeper/evidence": {"uids": ["synthetic:pr:4", "person:erin"]},
    "keeper/source_facts": {"uid": "system:Auth"},
    "keeper/project_claim": {
        "claims": [
            {
                "uid": "claim:plan",
                "kind": "fact",
                "subject": "system:Auth",
                "statement": "s",
                "value": None,
                "valid_from": None,
                "author": "keeper",
                "approved_by": "lead",
                "about": ["system:Auth"],
                "evidence": ["synthetic:pr:4"],
            }
        ]
    },  # fmt: skip
}


@pytest.mark.parametrize("name", sorted(UID_LOOKUPS))
def test_uid_lookups_are_index_scans(synthetic_graph, name):
    plan = db.explain(synthetic_graph, name, UID_LOOKUPS[name])
    assert any("Index Scan" in op for op in plan), plan
    assert not any("All Node Scan" in op for op in plan), plan


def test_keeper_notes_starts_from_the_claims(synthetic_graph):
    """The planner anchors on the Claim label (claims are few) and walks ABOUT to the uid: not
    an index lookup, but never a scan of every node."""
    plan = db.explain(synthetic_graph, "tools/keeper_notes", {"uid": "system:Auth"})
    assert any("Label Scan" in op for op in plan), plan
    assert not any("All Node Scan" in op for op in plan), plan


def test_the_kind_label_is_reported_whatever_the_label_order():
    """FalkorDB lists a node's labels in the order the graph first saw them, so with `Node`
    created first `labels(n)[0]` is 'Node' for every node. The kind (Person, WorkItem, ...) must
    still be what every query reports."""
    slug = "test_label_order"
    db.delete_graph(slug)
    try:
        db.run_text(slug, "CREATE INDEX FOR (n:Node) ON (n.uid)")  # Node is the first label
        load_company(synthetic_company(slug))
        db.run_text(slug, "MATCH (n) SET n:Node")
        first = db.run_text(slug, "MATCH (n) RETURN DISTINCT labels(n)[0]").result_set
        assert first == [["Node"]]  # the precondition this test is about

        counts = stats(slug)
        assert "node:Node" not in counts and counts["node:Person"] == 6
        assert tools.get_entity(slug, uid="synthetic:pr:4").label == "WorkItem"
        assert keeper.evidence(slug, ["person:erin"]) == {"person:erin": "Person"}
        assert keeper.source_facts(slug, "system:Auth").declared_owners == ["team:identity"]
        path = tools.path_between(slug, "person:erin", "system:Auth")[0]
        assert [n.label for n in path.nodes][0] == "Person"
        sources = db.run(slug, "sources/nodes_by_source", read_only=True)
        assert {r["label"] for r in sources} == {
            "Person", "Team", "System", "WorkItem", "Change", "Document", "Chunk",
        }  # fmt: skip
        people = db.run(slug, "graph/nodes", {"labels": ["Person"]}, read_only=True)
        assert len(people) == 6 and {r["label"] for r in people} == {"Person"}
        edges = db.run(slug, "graph/edges", {"labels": ["Person", "Team"]}, read_only=True)
        assert {e["rel"] for e in edges} == {"MEMBER_OF"}
    finally:
        db.delete_graph(slug)


def test_schema_backfills_the_node_label():
    """A graph loaded before the Node label existed is labelled by `brain schema`, once."""
    slug = "test_node_backfill"
    db.delete_graph(slug)
    try:
        load_company(synthetic_company(slug))
        db.run_text(slug, "MATCH (n) REMOVE n:Node")
        assert tools.get_entity(slug, uid="synthetic:pr:4") is None  # not a Node: not found
        total = db.run_text(slug, "MATCH (n) RETURN count(n)").result_set[0][0]

        assert schema.apply_schema(slug).backfilled == total
        assert tools.get_entity(slug, uid="synthetic:pr:4").label == "WorkItem"
        assert schema.apply_schema(slug).backfilled == 0  # idempotent
        assert stats(slug)["node:WorkItem"] == 15  # the label is added, nothing is duplicated
    finally:
        db.delete_graph(slug)
