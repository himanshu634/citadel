"""`run_cypher`: a query the agent writes runs read-only on one graph, with citable rows."""

from __future__ import annotations

import pytest
from brain import cypher, tools
from brain.cypher import CypherError, _value
from falkordb import Edge, Node, Path


def test_check_refuses_empty_and_load_csv():
    assert cypher.check("  MATCH (n) RETURN n ; ") == "MATCH (n) RETURN n"
    with pytest.raises(CypherError, match="empty"):
        cypher.check(" ; ")
    with pytest.raises(CypherError, match="LOAD CSV"):
        cypher.check("load  csv FROM 'https://example.com/x.csv' AS r RETURN r")


def test_nodes_edges_and_paths_become_citable_dicts():
    a = Node(1, labels=["Node", "Person"], properties={"uid": "person:a", "login": "a"})
    b = Node(2, labels=["WorkItem", "Node"], properties={"uid": "x:pr:1", "embedding": [0.1]})
    e = Edge(1, "AUTHORED", 2, properties={})
    ids = {1: "person:a", 2: "x:pr:1"}
    assert _value(a, ids) == {"label": "Person", "uid": "person:a", "login": "a"}
    assert _value(b, ids) == {"label": "WorkItem", "uid": "x:pr:1"}  # no embedding
    assert _value(e, ids) == {"type": "AUTHORED", "from": "person:a", "to": "x:pr:1"}
    path = _value(Path([a, b], [e]), ids)
    assert [n["uid"] for n in path["nodes"]] == ["person:a", "x:pr:1"]
    assert _value([0.5] * 768, ids) == "[vector of 768 numbers]"
    assert _value("x" * 5000, ids).endswith("…")


def test_column_names_make_dotted_uids_citable():
    assert cypher._column_names(["w.uid", "w.title", "p.uid", "uid"]) == [
        "w_uid", "w.title", "p_uid", "uid",
    ]  # fmt: skip


def test_run_cypher_reads_the_graph(synthetic_graph):
    r = tools.run_cypher(
        synthetic_graph,
        "MATCH (p:Person {login: $login})-[:AUTHORED]->(w:WorkItem) "
        "RETURN p.uid, w.uid AS uid, w.title AS title ORDER BY uid",
        {"login": "alice"},
        limit=1,
    )
    assert r.columns == ["p_uid", "uid", "title"]
    assert r.rows[0]["p_uid"] == "person:alice"
    assert r.row_count > 1 and r.truncated and len(r.rows) == 1


def test_run_cypher_returns_nodes_without_vectors(synthetic_graph):
    r = tools.run_cypher(synthetic_graph, "MATCH (c:Chunk) RETURN c LIMIT 1")
    chunk = r.rows[0]["c"]
    assert chunk["label"] == "Chunk" and chunk["uid"].startswith("chunk:")
    assert "embedding" not in chunk and "text_hash" not in chunk


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        ("CREATE (n:Person {uid: 'person:mallory'}) RETURN n", "only reads"),
        ("MATCH (n:Person) SET n.login = 'x' RETURN n", "only reads"),
        ("MATCH (n:Person) DETACH DELETE n", "only reads"),
        ("MATCH (n RETURN n", "Invalid input"),
        ("UNWIND range(1, 100000000) AS x WITH x WHERE x % 7 = 0 RETURN count(x)", "longer"),
    ],
)
def test_run_cypher_refuses_writes_and_reports_errors(synthetic_graph, monkeypatch, query, reason):
    monkeypatch.setattr(cypher, "TIMEOUT_MS", 20)
    with pytest.raises(CypherError, match=reason):
        tools.run_cypher(synthetic_graph, query)
    assert tools.run_cypher(
        synthetic_graph, "MATCH (p:Person {uid: 'person:mallory'}) RETURN count(p) AS n"
    ).rows == [{"n": 0}]


def test_run_cypher_on_a_missing_graph_has_no_rows():
    from brain.testing import falkordb_up

    if not falkordb_up():
        pytest.skip("FalkorDB not reachable (make up)")
    r = tools.run_cypher("test_no_such_graph", "MATCH (n) RETURN n.uid AS uid")
    assert r.rows == [] and not r.truncated
