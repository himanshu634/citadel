"""Territories on the Graph page: which system each node is drawn with (brain.graph_view)."""

from __future__ import annotations

from brain import graph_view
from brain.graph_view import NONE, OTHER, build, home_systems


def node(uid: str, label: str, title: str | None = None, **extra) -> dict:
    return {"uid": uid, "label": label, "title": title or uid, **extra}


def edge(source: str, rel: str, target: str) -> dict:
    return {"source": source, "rel": rel, "target": target}


def labels(rows: list[dict]) -> dict[str, str]:
    return {r["uid"]: r["label"] for r in rows}


def pairs(rows: list[dict]) -> list[tuple[str, str]]:
    return [(r["source"], r["target"]) for r in rows]


NODES = [
    node("system:auth", "System", "Auth"),
    node("system:web", "System", "Web"),
    node("change:1", "Change"),
    node("pr:1", "WorkItem"),
    node("issue:1", "WorkItem"),  # no system: follows the PR that closes it
    node("issue:2", "WorkItem"),  # linked to nothing
    node("person:ana", "Person"),
    node("doc:1", "Document"),
]
EDGES = [
    edge("change:1", "TOUCHES", "system:auth"),
    edge("change:1", "PART_OF", "pr:1"),
    edge("pr:1", "MENTIONS", "system:auth"),
    edge("pr:1", "CLOSES", "issue:1"),
    edge("person:ana", "AUTHORED", "pr:1"),
    edge("person:ana", "AUTHORED", "change:1"),
    edge("doc:1", "MENTIONS", "system:web"),
]


def test_each_node_finds_its_home_system():
    home = home_systems(labels(NODES), pairs(EDGES))
    assert home["system:auth"] == "system:auth"
    assert home["change:1"] == "system:auth"
    assert home["pr:1"] == "system:auth"
    assert home["issue:1"] == "system:auth"  # through the PR, not through a person
    assert home["person:ana"] == "system:auth"
    assert home["doc:1"] == "system:web"
    assert "issue:2" not in home


def test_a_work_item_does_not_take_a_home_through_a_person():
    rows = [node("system:a", "System"), node("p", "Person"), node("w", "WorkItem")]
    links = [edge("p", "AUTHORED", "w")]
    home = home_systems(labels(rows), pairs(links))
    assert "w" not in home and "p" not in home


def test_a_tie_goes_to_the_more_specific_system():
    rows = [
        node("system:src", "System"),
        node("system:src/graph", "System"),
        node("pr", "WorkItem"),
        node("other", "Change"),
    ]
    links = [
        edge("pr", "MENTIONS", "system:src"),
        edge("pr", "MENTIONS", "system:src/graph"),
        edge("other", "TOUCHES", "system:src"),  # src has more links: it is the broader one
    ]
    assert home_systems(labels(rows), pairs(links))["pr"] == "system:src/graph"


def test_small_systems_share_one_territory_and_homeless_nodes_another():
    view = build("t", NODES, EDGES, top=1)
    by_id = {t.id: t for t in view.territories}
    assert [t.id for t in view.territories] == ["system:auth", OTHER, NONE]
    assert by_id["system:auth"].name == "Auth" and by_id["system:auth"].size == 5
    assert by_id[OTHER].name == "1 smaller system" and by_id[OTHER].systems == 1
    assert by_id[OTHER].size == 2  # Web and the document about it
    assert by_id[NONE].name == "Not linked to code" and by_id[NONE].size == 1
    assert {n.uid: n.territory for n in view.nodes}["issue:2"] == NONE


def test_no_other_territory_when_every_system_fits():
    view = build("t", NODES, EDGES)
    assert OTHER not in {t.id for t in view.territories}


def test_bots_and_their_links_are_left_out_unless_asked():
    rows = [*NODES, node("person:ci-bot", "Person", is_bot=True)]
    links = [*EDGES, edge("person:ci-bot", "COMMENTED_ON", "pr:1")]
    hidden = build("t", rows, links)
    shown = build("t", rows, links, bots=True)
    assert "person:ci-bot" not in {n.uid for n in hidden.nodes}
    assert all("person:ci-bot" not in (e.source, e.target) for e in hidden.edges)
    assert hidden.bots == shown.bots == 1 and not hidden.bots_shown and shown.bots_shown
    assert {n.uid: n for n in shown.nodes}["person:ci-bot"].is_bot


def test_degree_counts_the_links_drawn():
    view = build("t", NODES, EDGES)
    degree = {n.uid: n.degree for n in view.nodes}
    assert degree["pr:1"] == 4 and degree["issue:2"] == 0


def test_an_empty_graph_is_an_empty_view():
    view = build("t", [], [])
    assert view.nodes == [] and view.edges == [] and view.territories == []


def test_the_same_graph_always_gives_the_same_map():
    first = build("t", NODES, EDGES, top=1)
    again = build("t", list(reversed(NODES)), list(reversed(EDGES)), top=1)
    assert {n.uid: n.territory for n in first.nodes} == {n.uid: n.territory for n in again.nodes}
    assert first.territories == again.territories


def test_kinds_are_the_six_brain_labels():
    assert set(graph_view.KINDS) == {"Person", "Team", "System", "WorkItem", "Change", "Document"}
