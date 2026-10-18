"""The whole company graph as the Graph page draws it: nodes, links and territories.

Why: the page shows every node at once, grouped into territories, one per system that the code
touches (design direction D). Which territory a node falls in is a rule of the product, not of
the drawing, so it lives here, pure and tested; the browser only lays the territories out.

A node's home system:
- a System is its own;
- a Change, Document, Team or WorkItem takes the system it has the most direct links to;
- a WorkItem with none takes the most common home of its non-person neighbours (two passes, so
  an issue a PR closes follows that PR);
- a Person takes the most common home of their neighbours.
A tie goes to the more specific system, the one with fewer links overall (a PR that names
`src` and `src/graph` once each lands in `src/graph`), then to the smaller uid, so the same graph
always gives the same map. The biggest
`TOP_TERRITORIES` systems get a territory each; the other systems share one ("N smaller
systems") and nodes with no home go to "Not linked to code".
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel

from brain import db

KINDS = ("Person", "Team", "System", "WorkItem", "Change", "Document")
TOP_TERRITORIES = 9
OTHER = "other"
NONE = "none"


class GraphNode(BaseModel):
    uid: str
    label: str  # the node kind: Person, Team, System, WorkItem, Change, Document
    title: str | None
    kind: str | None = None  # WorkItem: pull_request, issue, ...; Change: feat, fix, ...
    state: str | None = None  # WorkItem: open, closed, merged
    number: int | None = None
    url: str | None = None
    is_bot: bool = False
    comments: int = 0  # comment chunks folded into this node
    degree: int = 0  # links drawn to it (in this view)
    territory: str  # a Territory.id


class GraphEdge(BaseModel):
    source: str
    rel: str
    target: str


class NodeDetails(BaseModel):
    """Everything one node stores, for the hover card."""

    uid: str
    label: str
    props: dict[str, Any]


class LinkDetails(GraphEdge):
    """One relationship between two nodes and what it stores (source, count, pattern, ...)."""

    props: dict[str, Any]


class Territory(BaseModel):
    id: str  # the system's uid, "other" or "none"
    name: str
    system_uid: str | None  # the system it stands for; None for "other" and "none"
    size: int  # nodes in it
    systems: int  # System nodes in it


class GraphView(BaseModel):
    slug: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    territories: list[Territory]  # biggest first, then "other", then "none"
    bots: int  # bot accounts in the graph (shown or not)
    bots_shown: bool
    comments: int  # comment chunks folded into their work items


def _best(counts: Counter[str], weight: dict[str, int]) -> str | None:
    """The most frequent system; a tie goes to the one with fewer links, then the smaller uid."""
    if not counts:
        return None
    return min(counts, key=lambda k: (-counts[k], weight.get(k, 0), k))


def home_systems(
    nodes: dict[str, str], edges: Iterable[tuple[str, str]], passes: int = 2
) -> dict[str, str]:
    """Each node's home system uid (see the module doc). `nodes` maps uid -> label; `edges` are
    (source, target) pairs. Nodes without a home are left out."""
    adj: dict[str, list[str]] = defaultdict(list)
    for a, b in edges:
        if a in nodes and b in nodes:
            adj[a].append(b)
            adj[b].append(a)

    weight = {uid: len(adj[uid]) for uid, label in nodes.items() if label == "System"}

    def systems_of(uid: str) -> Counter[str]:
        return Counter(o for o in adj[uid] if nodes[o] == "System")

    home = {uid: uid for uid, label in nodes.items() if label == "System"}
    for uid, label in nodes.items():
        if label in ("Change", "Document", "Team", "WorkItem"):
            best = _best(systems_of(uid), weight)
            if best:
                home[uid] = best
    for _ in range(passes):  # each pass reads the homes the last pass knew
        known = dict(home)
        for uid, label in nodes.items():
            if label == "WorkItem" and uid not in known:
                best = _best(
                    Counter(known[o] for o in adj[uid] if nodes[o] != "Person" and o in known),
                    weight,
                )
                if best:
                    home[uid] = best
    known = dict(home)
    for uid, label in nodes.items():
        if label == "Person":
            best = _best(Counter(known[o] for o in adj[uid] if o in known), weight)
            if best:
                home[uid] = best
    return home


def territories(
    nodes: dict[str, str], titles: dict[str, str | None], home: dict[str, str], top: int
) -> tuple[dict[str, str], list[Territory]]:
    """Group homes into territories: (uid -> territory id, the territories)."""
    sizes = Counter(home.values())
    kept = sorted(sizes, key=lambda s: (-sizes[s], s))[:top]
    keep = set(kept)
    of = {
        uid: (home[uid] if home.get(uid) in keep else OTHER) if uid in home else NONE
        for uid in nodes
    }
    size = Counter(of.values())
    systems = Counter(of[uid] for uid, label in nodes.items() if label == "System")
    out = [
        Territory(id=s, name=titles.get(s) or s, system_uid=s, size=size[s], systems=systems[s])
        for s in kept
    ]
    if size[OTHER]:
        n = systems[OTHER]
        out.append(
            Territory(
                id=OTHER,
                name=f"{n} smaller system{'' if n == 1 else 's'}",
                system_uid=None,
                size=size[OTHER],
                systems=n,
            )
        )
    if size[NONE]:
        out.append(
            Territory(
                id=NONE, name="Not linked to code", system_uid=None, size=size[NONE], systems=0
            )
        )
    return of, out


def build(
    slug: str,
    node_rows: list[dict],
    edge_rows: list[dict],
    bots: bool = False,
    top: int = TOP_TERRITORIES,
) -> GraphView:
    """The view from the rows of graph/nodes and graph/edges. Without `bots`, bot accounts and
    their links are left out before territories are worked out."""
    bot_uids = {r["uid"] for r in node_rows if r.get("is_bot")}
    shown = [r for r in node_rows if bots or r["uid"] not in bot_uids]
    labels = {r["uid"]: r["label"] for r in shown}
    links = [r for r in edge_rows if r["source"] in labels and r["target"] in labels]
    home = home_systems(labels, ((r["source"], r["target"]) for r in links))
    of, terr = territories(labels, {r["uid"]: r.get("title") for r in shown}, home, top)
    degree = Counter(r["source"] for r in links) + Counter(r["target"] for r in links)
    nodes = [
        GraphNode(
            **{k: r.get(k) for k in ("uid", "label", "title", "kind", "state", "number", "url")},
            is_bot=bool(r.get("is_bot")),
            comments=int(r.get("comments") or 0),
            degree=degree[r["uid"]],
            territory=of[r["uid"]],
        )
        for r in shown
    ]
    return GraphView(
        slug=slug,
        nodes=nodes,
        edges=[GraphEdge(source=r["source"], rel=r["rel"], target=r["target"]) for r in links],
        territories=terr,
        bots=len(bot_uids),
        bots_shown=bots,
        comments=sum(int(r.get("comments") or 0) for r in node_rows),
    )


def load(slug: str, bots: bool = False) -> GraphView:
    """Read brain_<slug> and build its view. A graph that was never built is an empty view."""
    params = {"labels": list(KINDS)}
    node_rows = db.run(slug, "graph/nodes", params, read_only=True)
    edge_rows = db.run(slug, "graph/edges", params, read_only=True)
    return build(slug, node_rows, edge_rows, bots=bots)


# Vectors are numbers for the search index, not something a person reads.
HIDDEN_PROPS = frozenset({"embedding"})


def node_details(slug: str, uid: str) -> NodeDetails | None:
    """Every property one node stores, or None when the graph has no such node."""
    rows = db.run(slug, "graph/node", {"uid": uid}, read_only=True)
    if not rows:
        return None
    row = rows[0]
    props = {k: v for k, v in (row["props"] or {}).items() if k not in HIDDEN_PROPS}
    return NodeDetails(uid=row["uid"], label=row["label"], props=props)


def link_details(slug: str, a: str, b: str) -> list[LinkDetails]:
    """Every relationship between nodes `a` and `b`, either way round; empty when not linked."""
    rows = db.run(slug, "graph/link", {"a": a, "b": b}, read_only=True)
    return [
        LinkDetails(source=r["source"], rel=r["rel"], target=r["target"], props=r["props"] or {})
        for r in rows
    ]
