"""The Keeper's ledger store: named reads and writes on keeper_<slug>.

Why: the Keeper's records must survive a rebuild of brain_<slug>, so they live in their own
graph. Agent jobs reach them the way they reach the work layer, through the `WorkStore`
protocol (`agents/work/store.py`), so `runner.run_job` can run Keeper, pm and qa jobs against
this store:

    store.write("ledger/open_gap", "citadel_brain", {"uid": gap_uid(), "kind": ..., "now": now})
    store.read("ledger/gaps", {"statuses": ["open"], "limit": 10})

Two implementations with the same behaviour:
- `KeeperStore` runs `apps/brain/queries/ledger/<name>.cypher` on keeper_<slug>. Dedupe and
  guards (one live gap per question, guarded status moves, one running review) are in the Cypher.
- `MemoryKeeperStore` is the offline and test double: the same names, guards and row shapes in
  Python, under one lock (FalkorDB serialises the writes on a graph the same way).

Both check `acl` against keeper_<slug> (a read only when `db_user` is given), raise `KeyError`
for a name they do not know, fill the optional params (FalkorDB rejects a missing one), and turn
the runner's `work/write_episode` / `memory/write_episode` into a LogEntry with action "episode".
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any

from brain import db, queries
from pydantic import BaseModel
from redis.exceptions import ResponseError

from agents import acl
from agents.graphs import keeper_graph_name
from agents.keeper.model import (
    LIVE_GAP,
    NOTICING_KINDS,
    Gap,
    LogEntry,
    Review,
    iso,
    log_uid,
)

Row = dict[str, Any]

READS: tuple[str, ...] = (
    "ledger/get_gap",
    "ledger/gaps",
    "ledger/read_log",
    "ledger/review_current",
)

EPISODES: tuple[str, ...] = ("work/write_episode", "memory/write_episode")  # from runner.run_job

WRITES: tuple[str, ...] = (
    "ledger/open_gap",
    "ledger/set_gap_status",
    "ledger/log",
    "ledger/review_start",
    "ledger/review_finish",
    "ledger/review_stop_running",
    *EPISODES,
)

# Params a caller may leave out, and the value they mean. Every name a .cypher file references
# must be passed to FalkorDB, so the store fills these in for both implementations.
OPTIONAL: dict[str, dict[str, Any]] = {
    "ledger/open_gap": {"norm": None, "subject": None, "about": [], "trace_id": None},
    "ledger/set_gap_status": {"reason": None, "attempts_inc": 0},
    "ledger/log": {"why": None, "gap": None, "claim": None, "evidence": []},
    "ledger/read_log": {"gap": None, "claim": None},
    "ledger/review_finish": {"stop": None},
}

# Reads that return whole records: one column holding the node's properties, read back through
# its model so both stores give the same keys (FalkorDB does not store null properties).
RECORDS: dict[str, type[BaseModel]] = {
    "ledger/get_gap": Gap,
    "ledger/gaps": Gap,
    "ledger/read_log": LogEntry,
    "ledger/review_current": Review,
}


class _LedgerStore:
    """The part both stores share: names, permissions, optional params and episodes."""

    def __init__(self, slug: str) -> None:
        self.slug = slug
        self.graph = keeper_graph_name(slug)

    def read(
        self, name: str, params: Mapping[str, Any] | None = None, *, db_user: str | None = None
    ) -> list[Row]:
        if name not in READS:
            raise KeyError(f"no ledger read named {name!r}")
        if db_user is not None:
            acl.check(db_user, self.slug, self.graph, "R")
        return self._read(name, self._params(name, params or {}))

    def write(self, name: str, db_user: str, params: Mapping[str, Any]) -> list[Row]:
        if name not in WRITES:
            raise KeyError(f"no ledger write named {name!r}")
        acl.check(db_user, self.slug, self.graph, "W")
        if name in EPISODES:
            return self._episode(params)
        return self._write(name, self._params(name, params))

    def _params(self, name: str, params: Mapping[str, Any]) -> dict[str, Any]:
        extra = {"slug": self.slug} if name == "ledger/review_start" else {}
        return {**OPTIONAL.get(name, {}), **params, **extra}

    def _episode(self, p: Mapping[str, Any]) -> list[Row]:
        """A runner Episode as a log line: the agent did `input`; why = its summary; evidence =
        the actions it wrote. `now` is the runner's epoch int, stored as ISO like every `at`."""
        at = iso(p["now"])
        entry = {
            "uid": log_uid(at),
            "at": at,
            "actor": p["agent"],
            "action": "episode",
            "why": p.get("summary"),
            "gap": None,
            "claim": None,
            "evidence": list(p.get("actions") or []),
        }
        [row] = self._write("ledger/log", entry)
        return [{"episode": row["uid"]}]

    def _read(self, name: str, params: dict[str, Any]) -> list[Row]:
        raise NotImplementedError

    def _write(self, name: str, params: dict[str, Any]) -> list[Row]:
        raise NotImplementedError


# --- FalkorDB --------------------------------------------------------------------------------

_SCHEMA_DONE: set[str] = set()
_SCHEMA_LOCK = threading.Lock()


class KeeperStore(_LedgerStore):
    """The ledger in keeper_<slug> on FalkorDB."""

    def _graph(self):
        return db.client().select_graph(self.graph)

    def _schema(self) -> None:
        with _SCHEMA_LOCK:
            if self.graph in _SCHEMA_DONE:
                return
            g = self._graph()
            for stmt in queries.get("ledger/schema").statements():
                try:
                    g.query(stmt)
                except ResponseError as e:
                    if "already indexed" not in str(e):
                        raise
            _SCHEMA_DONE.add(self.graph)

    def _run(self, name: str, params: dict[str, Any], read_only: bool) -> list[Row]:
        g = self._graph()
        out: list[Row] = []
        for stmt in queries.get(name).statements():
            try:
                out = db.rows(g.ro_query(stmt, params) if read_only else g.query(stmt, params))
            except ResponseError:
                if read_only and self.graph not in db.client().list_graphs():
                    return []  # nothing written yet
                raise
        return out

    def _read(self, name: str, params: dict[str, Any]) -> list[Row]:
        rows = self._run(name, params, read_only=True)
        model = RECORDS.get(name)
        if model is None:
            return rows
        return [model(**next(iter(r.values()))).model_dump() for r in rows]

    def _write(self, name: str, params: dict[str, Any]) -> list[Row]:
        self._schema()
        return self._run(name, params, read_only=False)


def delete_keeper_graph(slug: str) -> bool:
    """Delete keeper_<slug> (backend reset, tests). False when it does not exist."""
    name = keeper_graph_name(slug)
    if name not in db.client().list_graphs():
        _SCHEMA_DONE.discard(name)
        return False
    db.client().select_graph(name).delete()
    _SCHEMA_DONE.discard(name)
    return True


# --- in memory -------------------------------------------------------------------------------


class MemoryKeeperStore(_LedgerStore):
    """The ledger in Python, for offline runs and tests. Mirrors the .cypher files."""

    def __init__(self, slug: str) -> None:
        super().__init__(slug)
        self.gaps: dict[str, Gap] = {}
        self.log: list[LogEntry] = []  # in write order (the Cypher's `seq`)
        self.reviews: list[Review] = []  # in start order
        self._lock = threading.RLock()

    def _read(self, name: str, params: dict[str, Any]) -> list[Row]:
        with self._lock:
            return getattr(self, "_r_" + name.split("/", 1)[1])(params)

    def _write(self, name: str, params: dict[str, Any]) -> list[Row]:
        with self._lock:
            return getattr(self, "_w_" + name.split("/", 1)[1])(params)

    # --- gaps ---------------------------------------------------------------------------------

    def _w_open_gap(self, p: Mapping[str, Any]) -> list[Row]:
        key = "subject" if p["kind"] in NOTICING_KINDS else "norm"
        live = sorted(
            (
                g
                for g in self.gaps.values()
                if g.kind == p["kind"]
                and g.status in LIVE_GAP
                and p[key] is not None
                and getattr(g, key) == p[key]
            ),
            key=lambda g: (g.created_at, g.uid),
        )
        trace = p["trace_id"]
        if live:
            g = live[0]
            g.count += 1
            g.updated_at = p["now"]
            if trace is not None and trace not in g.trace_ids:
                g.trace_ids.append(trace)
            g.about += [a for a in p["about"] if a not in g.about]
            return [{"uid": g.uid, "created": False, "count": g.count}]
        g = Gap(
            uid=p["uid"],
            kind=p["kind"],
            text=p["text"],
            norm=p["norm"],
            subject=p["subject"],
            created_at=p["now"],
            updated_at=p["now"],
            trace_ids=[] if trace is None else [trace],
            about=list(p["about"]),
        )
        self.gaps[g.uid] = g
        return [{"uid": g.uid, "created": True, "count": 1}]

    def _r_get_gap(self, p: Mapping[str, Any]) -> list[Row]:
        g = self.gaps.get(p["uid"])
        return [g.model_dump()] if g else []

    def _r_gaps(self, p: Mapping[str, Any]) -> list[Row]:
        rows = [g for g in self.gaps.values() if g.status in p["statuses"]]
        rows.sort(key=lambda g: (g.updated_at, g.uid), reverse=True)
        return [g.model_dump() for g in rows[: p["limit"]]]

    def _w_set_gap_status(self, p: Mapping[str, Any]) -> list[Row]:
        g = self.gaps.get(p["uid"])
        if g is None or g.status not in p["from"]:
            return []
        g.status = p["to"]
        g.reason = p["reason"]
        g.updated_at = p["now"]
        g.attempts += p["attempts_inc"]
        return [{"uid": g.uid, "status": g.status}]

    # --- log ----------------------------------------------------------------------------------

    def _w_log(self, p: Mapping[str, Any]) -> list[Row]:
        e = LogEntry(**{k: p[k] for k in LogEntry.model_fields})
        self.log.append(e)
        return [{"uid": e.uid}]

    def _r_read_log(self, p: Mapping[str, Any]) -> list[Row]:
        rows = [
            e
            for e in reversed(self.log)
            if (p["gap"] is None or e.gap == p["gap"])
            and (p["claim"] is None or e.claim == p["claim"])
        ]
        return [e.model_dump() for e in rows[: p["limit"]]]

    # --- reviews ------------------------------------------------------------------------------

    def _w_review_start(self, p: Mapping[str, Any]) -> list[Row]:
        if any(r.state == "running" for r in self.reviews):
            return []
        r = Review(
            uid=p["uid"],
            slug=p["slug"],
            trigger=p["trigger"],
            budget=p["budget"],
            started_at=p["now"],
        )
        self.reviews.append(r)
        return [{"uid": r.uid}]

    def _w_review_finish(self, p: Mapping[str, Any]) -> list[Row]:
        for r in self.reviews:
            if r.uid == p["uid"] and r.state == "running":
                r.state, r.stop, r.ended_at = p["state"], p["stop"], p["now"]
                return [{"uid": r.uid, "state": r.state}]
        return []

    def _r_review_current(self, p: Mapping[str, Any]) -> list[Row]:
        return [self.reviews[-1].model_dump()] if self.reviews else []

    def _w_review_stop_running(self, p: Mapping[str, Any]) -> list[Row]:
        out = []
        for r in self.reviews:
            if r.state == "running":
                r.state, r.stop, r.ended_at = "stopped", "restart", p["now"]
                out.append({"uid": r.uid})
        return out
