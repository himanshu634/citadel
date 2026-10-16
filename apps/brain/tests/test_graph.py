"""Loader and named tools against a real FalkorDB, on the synthetic company.

The synthetic data is designed with known answers (see examples/synthetic_company/generate.py).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from brain import db, tools
from brain.testing import load_company, needs_graph, synthetic_company
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
