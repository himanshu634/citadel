"""What one tool call touched in the graph, as a small subgraph the UI can draw.

Why: the Ask page draws the agent's walk through the company graph, one tool call at a time.
Only `path_between` and `get_entity` return relationships; the other tools return rows whose
fields name nodes (a person's teams, an expert's system). `subgraph` turns any tool's rows into
nodes and relationships with the graph's own uids, so the steps of one answer merge into one
picture. A relationship the rows only imply (an expert "works on" a system, two systems change
together) is marked `inferred`, and the UI draws it differently from a stored one.

Pure: no graph access. Rows are the tool's rows as JSON (what the toolset dumps).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from brain.canonical import person_uid, system_uid, team_uid

MAX_NODES = 40  # per step; a bigger result is drawn by its first nodes only

Row = dict[str, Any]


class _Builder:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.rels: dict[tuple[str, str, str], dict[str, Any]] = {}

    def node(self, uid: str | None, label: str, title: str | None = None, url: str | None = None):
        if not uid:
            return None
        node = self.nodes.get(uid)
        if node is None:
            if len(self.nodes) >= MAX_NODES:
                return None
            node = self.nodes[uid] = {"uid": uid, "label": label, "title": title or uid, "url": url}
        elif url and not node.get("url"):
            node["url"] = url
        return uid

    def rel(self, a: str | None, b: str | None, type_: str, *, inferred=False, note=None):
        if not a or not b or a not in self.nodes or b not in self.nodes or a == b:
            return
        key = (a, b, type_)
        if key not in self.rels:
            self.rels[key] = {"from": a, "to": b, "type": type_, "inferred": inferred}
            if note:
                self.rels[key]["note"] = note

    def person(self, login: str | None, uid: str | None = None) -> str | None:
        if not login and not uid:
            return None
        return self.node(uid or person_uid(login), "Person", login or uid)

    def team(self, name: str) -> str | None:
        return self.node(team_uid(name), "Team", name) if name else None

    def system(self, name: str | None, uid: str | None = None) -> str | None:
        if not name and not uid:
            return None
        return self.node(uid or system_uid(name), "System", name or uid)

    def item(self, row: Row) -> str | None:
        uid = row.get("uid")
        label = "Change" if ":commit:" in str(uid) else "WorkItem"
        number, title = row.get("number"), row.get("title")
        name = f"#{number} {title}" if number is not None and title else title
        if name is None and number is not None:
            name = f"#{number}"
        return self.node(uid, label, name, row.get("url"))

    def result(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return list(self.nodes.values()), list(self.rels.values())


# --- one function per tool ------------------------------------------------------------------


def _changes(n: Any) -> str | None:
    if not isinstance(n, int):
        return None
    return "1 change" if n == 1 else f"{n} changes"


def _person_profile(b: _Builder, params: Row, rows: list[Row]) -> None:
    for r in rows:
        me = b.person(r.get("login"), r.get("person_uid"))
        for t in r.get("teams") or []:
            b.rel(me, b.team(t), "MEMBER_OF")
        for s in r.get("systems") or []:
            note = _changes(s.get("changes"))
            b.rel(me, b.system(s.get("system")), "works on", inferred=True, note=note)
        for pr in r.get("recent_prs") or []:
            b.rel(me, b.item(pr), "AUTHORED")
        for pr in r.get("recent_reviews") or []:
            b.rel(me, b.item(pr), "REVIEWED")
        for s in r.get("owns") or []:
            b.rel(me, b.system(s), "OWNS")


def _experts_for_system(b: _Builder, params: Row, rows: list[Row]) -> None:
    for r in rows:
        sys = b.system(params.get("system"), r.get("system_uid"))
        who = b.person(r.get("login"), r.get("person_uid"))
        score = r.get("score")
        note = f"score {score:.2f}" if isinstance(score, int | float) else None
        b.rel(who, sys, "works on", inferred=True, note=note)
        for t in r.get("teams") or []:
            b.rel(who, b.team(t), "MEMBER_OF")


def _owners_vs_experts(b: _Builder, params: Row, rows: list[Row]) -> None:
    for r in rows:
        sys = b.system(r.get("system"), r.get("system_uid"))
        for c in r.get("top_contributors") or []:
            note = _changes(c.get("changes"))
            b.rel(b.person(c.get("login")), sys, "works on", inferred=True, note=note)


def _work_history(b: _Builder, params: Row, rows: list[Row]) -> None:
    for r in rows:
        sys = b.system(params.get("system"), r.get("system_uid"))
        it = b.item(r)
        b.rel(it, sys, r.get("via") or "TOUCHES", inferred=True)
        b.rel(b.person(r.get("author")), it, "AUTHORED")
        for rv in r.get("reviewers") or []:
            b.rel(b.person(rv.get("login")), it, "REVIEWED")
        for c in r.get("closes") or []:
            b.rel(it, b.item(c), "CLOSES")


def _impact_of(b: _Builder, params: Row, rows: list[Row]) -> None:
    base = b.system(params.get("system"))
    for r in rows:
        other = b.system(r.get("system"), r.get("system_uid"))
        n = r.get("co_changes")
        b.rel(base, other, "changed with", inferred=True, note=f"{n}×" if n is not None else None)
        for p in r.get("people") or []:
            b.rel(b.person(p.get("login")), other, "works on", inferred=True)


def _path_between(b: _Builder, params: Row, rows: list[Row]) -> None:
    for r in rows:
        for n in r.get("nodes") or []:
            b.node(n.get("uid"), n.get("label") or "Node", n.get("name"), n.get("url"))
        for rel in r.get("rels") or []:
            b.rel(rel.get("from"), rel.get("to"), rel.get("type") or "RELATED")


def _related_work_items(b: _Builder, params: Row, rows: list[Row]) -> None:
    for r in rows:
        it = b.item(r)
        b.rel(b.person(r.get("author")), it, "AUTHORED")
        for s in r.get("systems") or []:
            b.rel(it, b.system(s), "touches", inferred=True)
        for c in r.get("closes") or []:
            b.rel(it, b.item(c), "CLOSES")
        for c in r.get("closed_by") or []:
            b.rel(b.item(c), it, "CLOSES")


def _related_documents(b: _Builder, params: Row, rows: list[Row]) -> None:
    for r in rows:
        doc = b.node(r.get("uid"), "Document", r.get("title") or r.get("path"), r.get("url"))
        for s in r.get("systems") or []:
            b.rel(doc, b.system(s), "about", inferred=True)
        for m in r.get("mentions") or []:
            b.rel(doc, b.item(m), "MENTIONS")


def _semantic_search(b: _Builder, params: Row, rows: list[Row]) -> None:
    for r in rows:
        is_doc = r.get("label") == "Document"
        if is_doc:
            hit = b.node(r.get("uid"), "Document", r.get("title"), r.get("url"))
        else:
            hit = b.item(r)
        b.rel(b.person(r.get("author")), hit, "AUTHORED")
        for s in r.get("systems") or []:
            b.rel(hit, b.system(s), "about" if is_doc else "touches", inferred=True)


def _get_entity(b: _Builder, params: Row, rows: list[Row]) -> None:
    for r in rows:
        me = b.node(r.get("uid"), r.get("label") or "Node", r.get("title"), r.get("url"))
        for n in r.get("neighbours") or []:
            other = b.node(n.get("uid"), n.get("label") or "Node", n.get("title"), n.get("url"))
            a, z = (me, other) if n.get("direction") != "in" else (other, me)
            b.rel(a, z, n.get("rel") or "RELATED")


def _list_systems(b: _Builder, params: Row, rows: list[Row]) -> None:
    for r in rows:
        b.system(r.get("system"), r.get("system_uid"))


def _recent_work_items(b: _Builder, params: Row, rows: list[Row]) -> None:
    for r in rows:
        it = b.item(r)
        b.rel(b.person(r.get("author")), it, "AUTHORED")
        for s in r.get("systems") or []:
            b.rel(it, b.system(s), "touches", inferred=True)


def _people_activity(b: _Builder, params: Row, rows: list[Row]) -> None:
    for r in rows:
        me = b.person(r.get("login"), r.get("person_uid"))
        for t in r.get("teams") or []:
            b.rel(me, b.team(t), "MEMBER_OF")


_BY_TOOL: dict[str, Callable[[_Builder, Row, list[Row]], None]] = {
    "experts_for_system": _experts_for_system,
    "get_entity": _get_entity,
    "impact_of": _impact_of,
    "list_systems": _list_systems,
    "owners_vs_experts": _owners_vs_experts,
    "path_between": _path_between,
    "people_activity": _people_activity,
    "person_profile": _person_profile,
    "recent_work_items": _recent_work_items,
    "related_documents": _related_documents,
    "related_work_items": _related_work_items,
    "semantic_search": _semantic_search,
    "work_history": _work_history,
}


def subgraph(tool: str, params: Row, rows: list[Row]) -> tuple[list[dict], list[dict]]:
    """The nodes and relationships a call of `tool` touched. Unknown tools (and graph_stats,
    which names no node) touch nothing."""
    b = _Builder()
    build = _BY_TOOL.get(tool)
    if build is not None:
        build(b, params, [r for r in rows if isinstance(r, dict)])
    return b.result()


PREVIEW_ROWS = 25  # rows a step shows; the agent itself saw them all
PREVIEW_CHARS = 200  # a longer text field (a PR body, a doc snippet) is cut to this


def preview_rows(rows: list[Any]) -> list[Any]:
    """The first rows of a result with long text cut, small enough to send to the browser."""
    return [_cut(r) for r in rows[:PREVIEW_ROWS]]


def _cut(value: Any) -> Any:
    if isinstance(value, str) and len(value) > PREVIEW_CHARS:
        return value[:PREVIEW_CHARS] + "…"
    if isinstance(value, dict):
        return {k: _cut(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_cut(v) for v in value]
    return value
