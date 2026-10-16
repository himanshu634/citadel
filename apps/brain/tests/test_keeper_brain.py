"""The Keeper's brain side: evidence lookups, source facts, high-impact systems, projection of
accepted claims into brain_<slug>, noticing, and the `keeper_notes` read tool.

Runs on the shared synthetic graph. Projected test claims are retired, then deleted when the
module ends, so the other tests in the session see the graph as ingest left it.
"""

from __future__ import annotations

import math
import time

import pytest
from brain import db, keeper, queries, tools
from brain.testing import falkordb_up, needs_graph

pytestmark = needs_graph

PREFIX = "claim:test-keeper-"


@pytest.fixture(scope="module")
def brain(synthetic_graph):
    yield synthetic_graph
    # Test-only cleanup: retire is the product's way out; the node itself must not leak into
    # the other modules that share this session graph.
    db.graph(synthetic_graph).query(
        "MATCH (c:Claim) WHERE c.uid STARTS WITH $p DETACH DELETE c", {"p": PREFIX}
    )


def claim(uid: str, **over) -> dict:
    return {
        "uid": PREFIX + uid,
        "kind": "fact",
        "subject": "system:Auth",
        "statement": "Auth sessions expire after 12 hours.",
        "value": "12h",
        "about": ["system:Auth"],
        "evidence": ["synthetic:pr:4"],
        "valid_from": "2026-10-17T10:00:00Z",
        "author": "keeper",
        "approved_by": "auto",
        **over,
    }


def test_evidence_reports_only_existing(brain):
    assert keeper.evidence(brain, ["synthetic:pr:4", "nope"]) == {"synthetic:pr:4": "WorkItem"}
    assert keeper.evidence(brain, []) == {}


def test_source_facts_for_system(brain):
    facts = keeper.source_facts(brain, "system:Auth")
    assert facts.exists
    assert facts.top_expert == tools.call(brain, "experts_for_system", system="Auth")[0].person_uid
    assert facts.declared_owners == ["team:identity"]


def test_source_facts_for_other_subjects(brain):
    person = keeper.source_facts(brain, "person:erin")
    assert person.exists and person.declared_owners == [] and person.top_expert is None
    gone = keeper.source_facts(brain, "system:Nope")
    assert not gone.exists and gone.declared_owners == [] and gone.top_expert is None


def test_project_and_notes_round_trip(brain):
    c = claim("round-trip")
    assert keeper.project(brain, [c]) == []
    assert keeper.project(brain, [c]) == []  # idempotent: MERGE on uid

    notes = tools.call(brain, "keeper_notes", uid="system:Auth")
    mine = [n for n in notes if n.uid == c["uid"]]
    assert len(mine) == 1
    note = mine[0]
    assert (note.kind, note.statement, note.value) == ("fact", c["statement"], "12h")
    assert (note.valid_from, note.approved_by) == ("2026-10-17T10:00:00Z", "auto")
    assert [(e.uid, e.label) for e in note.evidence] == [("synthetic:pr:4", "WorkItem")]
    assert note.evidence[0].title

    entity = tools.get_entity(brain, uid="system:Auth", limit=200)
    claims = [n for n in entity.neighbours if n.label == "Claim"]
    assert [(n.uid, n.title, n.rel) for n in claims] == [(c["uid"], c["statement"], "ABOUT")]

    keeper.retire(brain, c["uid"], "superseded", "2026-10-18T10:00:00Z")
    assert c["uid"] not in {n.uid for n in tools.call(brain, "keeper_notes", uid="system:Auth")}
    node = tools.get_entity(brain, uid=c["uid"])
    assert node is not None and node.label == "Claim"  # retired, not deleted


def test_project_reports_missing_evidence(brain):
    gone = claim("missing-evidence", evidence=["gone:1"])
    no_subject = claim("missing-subject", subject="system:Nope", about=["system:Nope"])
    ok = claim("partly-there", evidence=["gone:2", "synthetic:pr:4"])
    missing = keeper.project(brain, [gone, no_subject, ok])
    assert sorted(missing) == sorted([gone["uid"], no_subject["uid"]])
    assert tools.get_entity(brain, uid=gone["uid"]) is None
    assert tools.get_entity(brain, uid=no_subject["uid"]) is None
    note = next(n for n in tools.keeper_notes(brain, "system:Auth") if n.uid == ok["uid"])
    assert [e.uid for e in note.evidence] == ["synthetic:pr:4"]
    keeper.retire(brain, ok["uid"], "superseded", "2026-10-18T10:00:00Z")


def test_high_impact_is_top_quarter(brain):
    # Four systems have a co-change partner, so the cut is ceil(4 * 0.25) = 1 system. Web app
    # and Billing each co-change with two systems (Auth and Infra with one): a tie at the cut,
    # so both are in.
    assert math.ceil(len(tools.list_systems(brain)) * 0.25) == 1
    assert keeper.high_impact_systems(brain) == {"system:Web app", "system:Billing"}


def test_notice_rows_shape(brain):
    for kind in ("stale_owner", "unowned_hot_system"):
        for row in keeper.notice(brain, kind, limit=10):
            assert row["subject"] and row["text"] and isinstance(row["about"], list)
    stale = keeper.notice(brain, "stale_owner", limit=10)
    assert [(r["subject"], r["about"]) for r in stale] == [
        ("system:Web app", ["system:Web app", "person:erin"])
    ]
    assert "erin" in stale[0]["text"] and "Web app" in stale[0]["text"]
    assert keeper.notice(brain, "unowned_hot_system", limit=10) == []  # every system is owned
    with pytest.raises(ValueError):
        keeper.notice(brain, "nonsense", limit=10)


@pytest.fixture
def hot_graph():
    """A tiny graph: Ledger (unowned, changed today), Old (unowned, changed a year ago),
    Owned (owned, changed today)."""
    if not falkordb_up():
        pytest.skip("FalkorDB not reachable (make up)")
    slug = "test_keeper_hot"
    db.delete_graph(slug)
    now = int(time.time())
    db.graph(slug).query(
        "CREATE (p:Person {uid: 'person:zoe', login: 'zoe', is_bot: false}),"
        " (l:System {uid: 'system:Ledger', name: 'Ledger'}),"
        " (o:System {uid: 'system:Old', name: 'Old'}),"
        " (w:System {uid: 'system:Owned', name: 'Owned'}),"
        " (p)-[:OWNS]->(w),"
        " (p)-[:AUTHORED]->(:Change {uid: 'c:1', ts: $now})-[:TOUCHES]->(l),"
        " (p)-[:AUTHORED]->(:Change {uid: 'c:2', ts: $now})-[:TOUCHES]->(l),"
        " (p)-[:AUTHORED]->(:Change {uid: 'c:3', ts: $old})-[:TOUCHES]->(o),"
        " (p)-[:AUTHORED]->(:Change {uid: 'c:4', ts: $now})-[:TOUCHES]->(w)",
        {"now": now, "old": now - 365 * 86_400},
    )
    yield slug
    db.delete_graph(slug)


def test_notice_unowned_hot_system(hot_graph):
    rows = keeper.notice(hot_graph, "unowned_hot_system", limit=10)
    assert [(r["subject"], r["about"]) for r in rows] == [
        ("system:Ledger", ["system:Ledger", "person:zoe"])
    ]
    assert "Ledger" in rows[0]["text"]


def test_ingest_never_writes_claims():
    for name in queries.list_names("load"):
        assert "Claim" not in queries.get(name).body, name
