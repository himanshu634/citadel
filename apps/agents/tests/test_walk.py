"""What each tool call draws on the Ask page: agents.walk (pure, no graph)."""

from __future__ import annotations

from agents import walk


def rels(rs):
    return {(r["from"], r["type"], r["to"], r["inferred"]) for r in rs}


def test_person_profile_links_teams_systems_and_work():
    row = {
        "login": "alice",
        "person_uid": "person:alice",
        "teams": ["identity"],
        "systems": [{"system": "Auth", "changes": 5, "last_ts": 1}],
        "recent_prs": [{"uid": "synthetic:pr:2", "number": 2, "title": "fix(auth): race"}],
        "recent_reviews": [{"uid": "synthetic:pr:10", "number": 10, "title": "refactor(auth)"}],
        "owns": [],
    }
    nodes, rs = walk.subgraph("person_profile", {"login": "alice"}, [row])
    labels = {n["uid"]: n["label"] for n in nodes}
    assert labels == {
        "person:alice": "Person",
        "team:identity": "Team",
        "system:Auth": "System",
        "synthetic:pr:2": "WorkItem",
        "synthetic:pr:10": "WorkItem",
    }
    assert rels(rs) == {
        ("person:alice", "MEMBER_OF", "team:identity", False),
        ("person:alice", "works on", "system:Auth", True),
        ("person:alice", "AUTHORED", "synthetic:pr:2", False),
        ("person:alice", "REVIEWED", "synthetic:pr:10", False),
    }
    titles = {n["uid"]: n["title"] for n in nodes}
    assert titles["synthetic:pr:2"] == "#2 fix(auth): race"
    assert next(r for r in rs if r["type"] == "works on")["note"] == "5 changes"


def test_experts_are_inferred_links_to_the_system_with_their_score():
    rows = [
        {"login": "carol", "person_uid": "person:carol", "score": 0.877, "teams": ["identity"],
         "system_uid": "system:Auth"},
        {"login": "dave", "person_uid": "person:dave", "score": 0.071, "teams": [],
         "system_uid": "system:Auth"},
    ]  # fmt: skip
    nodes, rs = walk.subgraph("experts_for_system", {"system": "Auth"}, rows)
    assert {n["uid"] for n in nodes} == {
        "system:Auth",
        "person:carol",
        "person:dave",
        "team:identity",
    }
    works = [r for r in rs if r["type"] == "works on"]
    assert all(r["inferred"] and r["to"] == "system:Auth" for r in works)
    assert [r["note"] for r in works] == ["score 0.88", "score 0.07"]


def test_path_between_keeps_the_stored_relationships():
    row = {
        "length": 2,
        "nodes": [
            {"label": "Person", "uid": "person:alice", "name": "alice", "url": None},
            {"label": "WorkItem", "uid": "synthetic:pr:10", "name": "refactor", "url": "u"},
            {"label": "Person", "uid": "person:carol", "name": "carol", "url": None},
        ],
        "rels": [
            {"type": "REVIEWED", "from": "person:alice", "to": "synthetic:pr:10"},
            {"type": "AUTHORED", "from": "person:carol", "to": "synthetic:pr:10"},
        ],
    }
    nodes, rs = walk.subgraph("path_between", {}, [row])
    assert [n["uid"] for n in nodes] == ["person:alice", "synthetic:pr:10", "person:carol"]
    assert rels(rs) == {
        ("person:alice", "REVIEWED", "synthetic:pr:10", False),
        ("person:carol", "AUTHORED", "synthetic:pr:10", False),
    }


def test_get_entity_points_incoming_neighbours_at_the_entity():
    row = {
        "uid": "synthetic:pr:10",
        "label": "WorkItem",
        "title": "refactor(auth)",
        "url": "u",
        "neighbours": [
            {"rel": "AUTHORED", "direction": "in", "uid": "person:carol", "label": "Person",
             "title": "carol", "url": None},
            {"rel": "TOUCHES", "direction": "out", "uid": "system:Auth", "label": "System",
             "title": "Auth", "url": None},
        ],
    }  # fmt: skip
    _, rs = walk.subgraph("get_entity", {"uid": "synthetic:pr:10"}, [row])
    assert rels(rs) == {
        ("person:carol", "AUTHORED", "synthetic:pr:10", False),
        ("synthetic:pr:10", "TOUCHES", "system:Auth", False),
    }


def test_work_history_marks_commits_as_changes():
    row = {
        "uid": "synthetic:commit:a001",
        "number": None,
        "title": "feat(auth): add JWT",
        "via": "TOUCHES",
        "author": "alice",
        "reviewers": [{"login": "carol", "state": "APPROVED"}],
        "closes": [],
        "system_uid": "system:Auth",
    }
    nodes, rs = walk.subgraph("work_history", {"system": "Auth"}, [row])
    assert {n["uid"]: n["label"] for n in nodes}["synthetic:commit:a001"] == "Change"
    assert ("person:carol", "REVIEWED", "synthetic:commit:a001", False) in rels(rs)


def test_a_step_draws_at_most_max_nodes_and_no_dangling_links():
    rows = [{"login": f"p{i}", "person_uid": f"person:p{i}", "teams": [f"t{i}"]} for i in range(60)]
    nodes, rs = walk.subgraph("people_activity", {}, rows)
    uids = {n["uid"] for n in nodes}
    assert len(nodes) == walk.MAX_NODES
    assert all(r["from"] in uids and r["to"] in uids for r in rs)


def test_unknown_tools_and_stats_draw_nothing():
    assert walk.subgraph("graph_stats", {}, [{"kind": "node", "type": "Person"}]) == ([], [])
    assert walk.subgraph("no_such_tool", {}, [{"uid": "x"}]) == ([], [])


def test_preview_rows_cuts_rows_and_long_text():
    rows = [{"body": "x" * 500, "nested": [{"snippet": "y" * 300}]}] * 30
    out = walk.preview_rows(rows)
    assert len(out) == walk.PREVIEW_ROWS
    assert len(out[0]["body"]) == walk.PREVIEW_CHARS + 1 and out[0]["body"].endswith("…")
    assert out[0]["nested"][0]["snippet"].endswith("…")
