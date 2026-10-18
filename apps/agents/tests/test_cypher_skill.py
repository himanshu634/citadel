"""The Cypher skill Ask reads before writing a `run_cypher` query: in the prompt, in step with
the graph's schema, and every example a query that runs."""

from __future__ import annotations

import re

import pytest
from agents import skills
from agents.loop import SYSTEM_PROMPT
from agents.walk import subgraph
from brain import queries, tools

SKILL = skills.load("cypher")
INTERNAL = {"Node", "SyncState", "Decision", "Episode"}


def _schema_names() -> tuple[set[str], set[str]]:
    """Labels and relationship types written by the load and Keeper queries."""
    text = "\n".join(
        line
        for folder in ("load", "keeper")
        for p in (queries.QUERIES_DIR / folder).glob("*.cypher")
        for line in p.read_text().splitlines()
        if not line.lstrip().startswith("//")
    )
    labels = set(re.findall(r"[(:]\w*:([A-Z][A-Za-z]+)\b", text))
    rels = set(re.findall(r"\[\w*:([A-Z_]{3,})", text))
    return labels - INTERNAL, rels


def test_the_skill_is_in_asks_prompt_without_front_matter():
    assert SKILL.startswith("# Writing a query for `run_cypher`")
    assert SYSTEM_PROMPT.rstrip().endswith(SKILL)
    assert "name: graph-cypher" not in SYSTEM_PROMPT
    assert "run_cypher" in tools.TOOLS


def test_the_skill_names_every_label_and_relationship():
    labels, rels = _schema_names()
    assert {"Person", "WorkItem", "Chunk", "Claim"} <= labels
    assert {"AUTHORED", "BLOCKS", "SUPERSEDED_BY"} <= rels
    missing = sorted(n for n in labels | rels if f"`{n}`" not in SKILL and f":{n}]" not in SKILL)
    assert not missing, f"cypher SKILL.md does not describe {missing}"


def test_every_skill_example_runs(synthetic_graph):
    examples = re.findall(r"```cypher\n(.*?)```", SKILL, re.S)
    assert len(examples) >= 5
    params = {"a": "Auth", "b": "Billing", "login": "alice", "system": "Billing", "uid": "x"}
    for query in examples:
        tools.run_cypher(synthetic_graph, query, params)  # raises on a broken example


def test_a_query_step_draws_the_nodes_and_relationships_it_returned():
    rows = [{
        "columns": ["p", "r", "w_uid"],
        "rows": [{
            "p": {"label": "Person", "uid": "person:erin", "login": "erin"},
            "r": {"type": "REVIEWED", "from": "person:erin", "to": "x:pr:4"},
            "w_uid": "x:pr:4",
        }],
        "row_count": 1,
        "truncated": False,
    }]  # fmt: skip
    nodes, rels = subgraph("run_cypher", {}, rows)
    assert {(n["uid"], n["label"]) for n in nodes} == {
        ("person:erin", "Person"), ("x:pr:4", "WorkItem"),
    }  # fmt: skip
    assert rels == [{"from": "person:erin", "to": "x:pr:4", "type": "REVIEWED", "inferred": False}]


@pytest.mark.parametrize("uid", ["chunk:x:comment:1", "claim:abc"])
def test_chunk_and_claim_uids_get_their_label(uid):
    nodes, _ = subgraph("run_cypher", {}, [{"rows": [{"n_uid": uid}]}])
    assert nodes[0]["label"] == ("Chunk" if uid.startswith("chunk") else "Claim")
