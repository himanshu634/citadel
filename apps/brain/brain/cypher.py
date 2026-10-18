"""The `run_cypher` tool: one read query written by the agent, run on brain_<slug>.

Why: the named tools answer the questions we foresaw. A question none of them fits (a count by
an unusual property, a pattern three hops long) needs a query of its own. This module is the
one place such text runs, with fixed guards around it:

- read only: `db.run_cypher` sends GRAPH.RO_QUERY, so the server refuses any write;
- one graph: the query can only see brain_<slug>, which `db` selects;
- nothing outside the graph: `check` refuses LOAD CSV (a read query may fetch a URL or file),
  also when a comment sits between the two words;
- bounded: `check` wants a LIMIT (without one, FalkorDB sends every row before any cut), a
  server-side timeout, and at most `limit` rows come back (`truncated` says so);
- citable: nodes become dicts with `uid` and `label`, a column `w.uid` is renamed `w_uid`, and
  embedding vectors and long texts are cut, so the rows fit the agent's context and every node
  in them can be cited.

How to write a query for this graph is in `agents/skills/cypher/SKILL.md`, which Ask reads in
its system prompt.
"""

from __future__ import annotations

import re
from typing import Any

from falkordb import Edge, Node, Path
from pydantic import BaseModel, ConfigDict, Field

from brain import db

TIMEOUT_MS = 5_000
MAX_TEXT = 1_500  # a longer string value (a PR body, a chunk's text) is cut to this
HIDDEN = frozenset({"embedding", "embedded_hash", "text_hash", "company"})
_LOAD = re.compile(r"\bLOAD\b", re.IGNORECASE)
_CSV = re.compile(r"\bCSV\b", re.IGNORECASE)
_LIMIT = re.compile(r"\bLIMIT\b", re.IGNORECASE)


class CypherError(ValueError):
    """A query this tool refuses or the server could not run, said in one sentence the agent
    can act on."""


class CypherParams(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str = Field(
        description="One read-only openCypher statement for FalkorDB (MATCH ... RETURN ...). "
        "Alias every returned uid AS uid or AS <thing>_uid so it can be cited."
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description='Values for $name placeholders in the query, e.g. {"login": "alice"}.',
    )
    limit: int = Field(50, ge=1, le=200, description="Most rows to return.")


class CypherResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int  # rows the query returned, before `limit`
    truncated: bool


def check(query: str) -> str:
    """The query text to run, or CypherError when this tool will not run it."""
    text = query.strip().rstrip(";").strip()
    if not text:
        raise CypherError("the query is empty")
    # Both words anywhere, not "LOAD CSV" as written: `LOAD /* x */ CSV` runs too. A literal
    # with these words can go in `params`.
    if _LOAD.search(text) and _CSV.search(text):
        raise CypherError("LOAD CSV is not allowed: query only the graph")
    if not _LIMIT.search(text):
        raise CypherError("add a LIMIT to the query (at most 200 rows come back anyway)")
    return text


def run(slug: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Run one checked read query; always one result row (columns, rows, truncated)."""
    p = CypherParams.model_validate(params)
    text = check(p.query)
    try:
        columns, raw = db.run_cypher(slug, text, p.params or None, TIMEOUT_MS)
    except Exception as e:
        raise CypherError(_reason(e)) from e
    ids = _node_uids(raw[: p.limit])
    names = _column_names(columns)
    rows = [
        {name: _value(v, ids) for name, v in zip(names, r, strict=True)} for r in raw[: p.limit]
    ]
    result = CypherResult(
        columns=names, rows=rows, row_count=len(raw), truncated=len(raw) > p.limit
    )
    return [result.model_dump()]


def _reason(e: Exception) -> str:
    message = str(e).strip() or type(e).__name__
    if "timed out" in message.lower():
        return (
            f"the query ran longer than {TIMEOUT_MS // 1000} s: start from an indexed lookup "
            "(a uid, a name, full-text) and cut variable-length paths shorter"
        )
    if "read-only" in message:
        return "the query writes; only reads are allowed"
    return message


def _column_names(columns: list[str]) -> list[str]:
    """`w.uid` -> `w_uid` (so the agent can cite it); other names as written."""
    out: list[str] = []
    for c in columns:
        name = re.sub(r"\W+", "_", c).strip("_") if c.endswith(".uid") else c
        while name in out:
            name += "_"
        out.append(name)
    return out


def _node_uids(raw: list[list[Any]]) -> dict[int, str]:
    """Internal node id -> uid for every node in the result, so an edge can name its ends."""
    ids: dict[int, str] = {}

    def walk(v: Any) -> None:
        if isinstance(v, Node):
            uid = (v.properties or {}).get("uid")
            if v.id is not None and isinstance(uid, str):
                ids[v.id] = uid
        elif isinstance(v, Path):
            for n in v.nodes():
                walk(n)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)

    walk(raw)
    return ids


def _value(v: Any, ids: dict[int, str]) -> Any:
    if isinstance(v, Node):
        labels = v.labels if isinstance(v.labels, list) else [v.labels]
        kind = next((lab for lab in labels if lab and lab != "Node"), None)
        props = {k: _value(x, ids) for k, x in (v.properties or {}).items() if k not in HIDDEN}
        return {"label": kind, **props}
    if isinstance(v, Edge):
        return {
            "type": v.relation,
            "from": _end(v.src_node, ids),
            "to": _end(v.dest_node, ids),
            **{k: _value(x, ids) for k, x in (v.properties or {}).items() if k not in HIDDEN},
        }
    if isinstance(v, Path):
        return {
            "nodes": [_value(n, ids) for n in v.nodes()],
            "rels": [_value(e, ids) for e in v.edges()],
        }
    if isinstance(v, dict):
        return {k: _value(x, ids) for k, x in v.items() if k not in HIDDEN}
    if isinstance(v, (list, tuple)):
        if len(v) > 32 and all(isinstance(x, float) for x in v):
            return f"[vector of {len(v)} numbers]"
        return [_value(x, ids) for x in v]
    if isinstance(v, str) and len(v) > MAX_TEXT:
        return v[:MAX_TEXT] + "…"
    return v


def _end(node: Any, ids: dict[int, str]) -> str | None:
    if isinstance(node, Node):
        uid = (node.properties or {}).get("uid")
        return uid if isinstance(uid, str) else ids.get(node.id) if node.id is not None else None
    return ids.get(node) if isinstance(node, int) else None
