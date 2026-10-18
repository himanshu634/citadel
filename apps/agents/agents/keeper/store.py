"""The Keeper's ledger store: named reads and writes on keeper_<slug>.

Why: the Keeper's records must survive a rebuild of brain_<slug>, so they live in their own
graph. Agent jobs reach them through the `WorkStore` protocol (`agents/work/store.py`), so
`runner.run_job` can run Keeper, pm and qa jobs against this store:

    store.write("ledger/open_gap", "citadel_brain", {"uid": gap_uid(), "kind": ..., "now": now})
    store.read("ledger/gaps", {"statuses": ["open"], "limit": 10})

Two implementations with the same behaviour:
- `KeeperStore` runs `apps/brain/queries/ledger/<name>.cypher` on keeper_<slug>. Dedupe and
  guards (one live gap per question, one consult per role per gap, one follow-up per claim,
  guarded gap and claim status moves, a gap asks the Archivist once, one running review, a step
  finished once) are in the
  Cypher: `review_start` starts nothing while a review is running, `review_stop_running`
  stops every running one (`backend.keeper_runs`: their run is gone). A review's steps
  (`ledger/write_step`, `finish_step`, `review_steps`) are the activity trail's; a step's
  `input` is stored as JSON text and read back as a dict.
- `MemoryKeeperStore` is the offline and test double: the same names, guards and row shapes in
  Python, under one lock (FalkorDB serialises the writes on a graph the same way).

Both check `acl` against keeper_<slug> (a read only when `db_user` is given), raise `KeyError`
for a name they do not know, fill the optional params (FalkorDB rejects a missing one), and turn
the runner's `ledger/write_episode` into a LogEntry with action "episode".
"""

from __future__ import annotations

import copy
import json
import re
import threading
from collections.abc import Mapping
from typing import Any, get_args

from brain import db, queries
from pydantic import BaseModel
from redis.exceptions import ResponseError

from agents import acl
from agents.graphs import keeper_graph_name
from agents.keeper.model import (
    LIVE_GAP,
    LIVE_REQUEST,
    NOTICING_KINDS,
    ArchiveFind,
    ArchiveRequest,
    Claim,
    ClaimStatus,
    Consult,
    FollowUp,
    Gap,
    GapStatus,
    LogEntry,
    RequestOutcome,
    RequestStatus,
    Review,
    ReviewStep,
    consult_uid,
    followup_uid,
    iso,
    log_uid,
)

Row = dict[str, Any]

READS: tuple[str, ...] = (
    "ledger/get_gap",
    "ledger/gaps",
    "ledger/latest_gap_for_subject",
    "ledger/read_log",
    "ledger/review_current",
    "ledger/recent_reviews",
    "ledger/review_steps",
    "ledger/queue_consult",
    "ledger/consults_for_gap",
    "ledger/get_claim",
    "ledger/claims",
    "ledger/claims_for_subject",
    "ledger/claims_for_gap",
    "ledger/queue_follow_up",
    "ledger/followups",
    "ledger/archive_get_request",
    "ledger/archive_queue",
    "ledger/archive_finds",
    "ledger/archive_recall",
    "ledger/archive_requests",
    "ledger/archive_requests_for_gap",
)

EPISODES: tuple[str, ...] = ("ledger/write_episode",)  # from runner.run_job

WRITES: tuple[str, ...] = (
    "ledger/open_gap",
    "ledger/set_gap_status",
    "ledger/gap_archive_asked",
    "ledger/log",
    "ledger/review_start",
    "ledger/review_finish",
    "ledger/review_stop_running",
    "ledger/review_picked",
    "ledger/write_step",
    "ledger/finish_step",
    "ledger/post_consult",
    "ledger/answer_consult",
    "ledger/write_claim",
    "ledger/set_claim_status",
    "ledger/open_followup",
    "ledger/follow_up_tried",
    "ledger/archive_open_request",
    "ledger/archive_set_request",
    "ledger/archive_write_find",
    *EPISODES,
)

# Params a caller may leave out, and the value they mean. Every name a .cypher file references
# must be passed to FalkorDB, so the store fills these in for both implementations.
OPTIONAL: dict[str, dict[str, Any]] = {
    "ledger/open_gap": {"norm": None, "subject": None, "about": [], "trace_id": None},
    "ledger/set_gap_status": {"reason": None, "attempts_inc": 0},
    "ledger/log": {"why": None, "gap": None, "claim": None, "evidence": []},
    "ledger/read_log": {"gap": None, "claim": None},
    "ledger/review_finish": {"stop": None, "archive_reopened": []},
    "ledger/post_consult": {"archive": False},
    "ledger/review_picked": {"gap_text": None},
    "ledger/write_step": {
        "kind": "graph",
        "input": {},
        "status": "running",
        "count": None,
        "error": None,
        "touched": [],
    },
    "ledger/finish_step": {"count": None, "error": None, "touched": []},
    "ledger/answer_consult": {
        "kind": None,
        "subject": None,
        "statement": None,
        "value": None,
        "cites": [],
    },
    "ledger/set_claim_status": {"by": None, "why": None, "valid_to": None, "conflict": None},
    "ledger/open_followup": {"body": "", "by": "pm"},
    "ledger/followups": {"status": None},
    "ledger/archive_open_request": {
        "refs": [],
        "from_uid": None,
        "gap": None,
        "thread": None,
    },
    "ledger/archive_set_request": {
        "outcome": None,
        "summary": None,
        "reason": None,
        "partial": False,
        "calls": 0,
    },
    "ledger/archive_write_find": {
        "url": None,
        "date": None,
        "evidence": [],
        "superseded_by": None,
    },
}

# Params that hold a timestamp. Each is stored as ISO text (`model.iso`).
TIMESTAMPS: tuple[str, ...] = (
    "now",
    "at",
    "created_at",
    "updated_at",
    "valid_from",
    "valid_to",
)

# Reads that return whole records: one column holding the node's properties, read back through
# its model so both stores give the same keys (FalkorDB does not store null properties).
RECORDS: dict[str, type[BaseModel]] = {
    "ledger/get_gap": Gap,
    "ledger/gaps": Gap,
    "ledger/latest_gap_for_subject": Gap,
    "ledger/read_log": LogEntry,
    "ledger/review_current": Review,
    "ledger/recent_reviews": Review,
    "ledger/review_steps": ReviewStep,
    "ledger/queue_consult": Consult,
    "ledger/consults_for_gap": Consult,
    "ledger/get_claim": Claim,
    "ledger/claims": Claim,
    "ledger/claims_for_subject": Claim,
    "ledger/claims_for_gap": Claim,
    "ledger/queue_follow_up": Claim,
    "ledger/followups": FollowUp,
    "ledger/archive_get_request": ArchiveRequest,
    "ledger/archive_queue": ArchiveRequest,
    "ledger/archive_recall": ArchiveRequest,
    "ledger/archive_requests": ArchiveRequest,
    "ledger/archive_requests_for_gap": ArchiveRequest,
    "ledger/archive_finds": ArchiveFind,
}


_UID = re.compile(r"[a-z_]+:\S+")  # a uid, e.g. claim:1a2b3c4d5e6f (not an action name)

_STATUS: dict[str, tuple[str, ...]] = {
    "ledger/set_gap_status": get_args(GapStatus),
    "ledger/set_claim_status": get_args(ClaimStatus),
    "ledger/archive_set_request": get_args(RequestStatus),
    "ledger/write_step": ("running", "done", "failed"),
    "ledger/finish_step": ("done", "failed"),
}
_STATUS_KEY = {"ledger/write_step": "status", "ledger/finish_step": "status"}  # else "to"


def _validate(name: str, p: dict[str, Any]) -> None:
    """Refuse a bad write before anything is stored (a ValueError; pydantic's ValidationError is
    one): an unknown status, or a gap or claim its model rejects. A claim's timestamps default
    to `now`, and the claim is written as its model dumps it. A step's `input` is stored as
    JSON text (FalkorDB holds no maps)."""
    key = _STATUS_KEY.get(name, "to")
    if name in _STATUS and p.get(key) not in _STATUS[name]:
        raise ValueError(f"{name}: unknown status {p.get(key)!r}")
    if name == "ledger/write_step":
        given = p["input"]
        step_input = json.loads(given) if isinstance(given, str) else given  # bad JSON: ValueError
        if not isinstance(step_input, dict):
            raise ValueError(f"{name}: input must be a JSON object, not {given!r}"[:200])
        p["input"] = json.dumps(step_input, default=str, ensure_ascii=False)
    if name == "ledger/open_gap":
        trace = p.get("trace_id")
        Gap(
            uid=p.get("uid"),
            kind=p.get("kind"),
            text=p.get("text"),
            norm=p.get("norm"),
            subject=p.get("subject"),
            about=p.get("about"),
            trace_ids=[] if trace is None else [trace],
            created_at=p.get("now"),
            updated_at=p.get("now"),
        )
    if name == "ledger/archive_open_request":
        if not str(p.get("norm") or "").strip():
            raise ValueError(f"{name}: norm is empty")
        fields = {k: p[k] for k in ArchiveRequest.model_fields if k in p}
        ArchiveRequest(**fields, created_at=p.get("now"), updated_at=p.get("now"))
    outcomes = (None, *get_args(RequestOutcome))
    if name == "ledger/archive_set_request" and p.get("outcome") not in outcomes:
        raise ValueError(f"{name}: unknown outcome {p['outcome']!r}")
    if name == "ledger/archive_write_find":
        ArchiveFind(**{k: p[k] for k in ArchiveFind.model_fields if k in p})
    if name == "ledger/write_claim":
        for key in ("created_at", "updated_at"):
            if p.get(key) is None:
                p[key] = p.get("now")
        p.update(Claim(**{k: p[k] for k in Claim.model_fields if k in p}).model_dump())


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
        p = self._params(name, params)
        _validate(name, p)
        return self._write(name, p)

    def _params(self, name: str, params: Mapping[str, Any]) -> dict[str, Any]:
        """Fill the optional params; store every timestamp as ISO text (job writes pass
        `Ctx.now`, an epoch int, and the ledger sorts timestamps as text)."""
        extra = {"slug": self.slug} if name == "ledger/review_start" else {}
        p = {**copy.deepcopy(OPTIONAL.get(name, {})), **params, **extra}
        for key in TIMESTAMPS:
            if p.get(key) is not None:
                p[key] = iso(p[key])
        return p

    def _episode(self, p: Mapping[str, Any]) -> list[Row]:
        """A runner Episode as a log line. The runner's `input` is "<role>.<job> <subject uid>":
        a gap: or claim: subject fills `gap` / `claim`, so the gap's or claim's log shows the
        run; why = "<input>: <summary>"; evidence = the uids among the actions it wrote. `now`
        is the runner's epoch int, stored as ISO like every `at`."""
        at = iso(p["now"])
        job = p.get("input") or ""
        subject = job.split()[-1] if job.split() else ""
        summary = p.get("summary")
        entry = {
            "uid": log_uid(at),
            "at": at,
            "actor": p["agent"],
            "action": "episode",
            "why": f"{job}: {summary}" if job and summary else (summary or job or None),
            "gap": subject if subject.startswith("gap:") else None,
            "claim": subject if subject.startswith("claim:") else None,
            "evidence": [a for a in p.get("actions") or [] if _UID.fullmatch(str(a))],
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
        self.steps: dict[tuple[str, int], dict[str, Any]] = {}  # (review, n) -> stored props
        self.consults: dict[str, Consult] = {}
        self.claims: dict[str, Claim] = {}
        self.followups: dict[str, FollowUp] = {}
        self.requests: dict[str, ArchiveRequest] = {}
        self.finds: dict[tuple[str, str], ArchiveFind] = {}  # (request, item uid)
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
            if trace is None or trace not in g.trace_ids:  # one trace is one sighting
                g.count += 1
                g.updated_at = p["now"]
                if trace is not None:
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

    def _r_latest_gap_for_subject(self, p: Mapping[str, Any]) -> list[Row]:
        rows = [g for g in self.gaps.values() if (g.kind, g.subject) == (p["kind"], p["subject"])]
        rows.sort(key=lambda g: (g.created_at, g.uid), reverse=True)
        return [g.model_dump() for g in rows[:1]]

    def _w_set_gap_status(self, p: Mapping[str, Any]) -> list[Row]:
        g = self.gaps.get(p["uid"])
        if g is None or g.status not in p["from"]:
            return []
        g.status = p["to"]
        g.reason = p["reason"]
        g.updated_at = p["now"]
        g.attempts += p["attempts_inc"]
        return [{"uid": g.uid, "status": g.status}]

    def _w_gap_archive_asked(self, p: Mapping[str, Any]) -> list[Row]:
        g = self.gaps.get(p["uid"])
        if g is None or g.archive_asked:
            return []
        g.archive_asked = True
        return [{"uid": g.uid}]

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
                r.archive_reopened = list(p["archive_reopened"])
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

    def _r_recent_reviews(self, p: Mapping[str, Any]) -> list[Row]:
        shown = [r for r in reversed(self.reviews) if r.state != "skipped"]
        return [r.model_dump() for r in shown[: p["limit"]]]

    def _w_review_picked(self, p: Mapping[str, Any]) -> list[Row]:
        for r in self.reviews:
            if r.uid == p["uid"]:
                r.gaps, r.gap_text = list(p["gaps"]), p["gap_text"]
                return [{"uid": r.uid}]
        return []

    # --- review steps -------------------------------------------------------------------------

    def _w_write_step(self, p: Mapping[str, Any]) -> list[Row]:
        if p["review"] not in self.requests and not any(r.uid == p["review"] for r in self.reviews):
            return []  # steps hang off a review or an archive request
        keys = ("review", "n", "actor", "tool", "kind", "input", "status", "count", "error")
        self.steps[(p["review"], p["n"])] = {
            **{k: p[k] for k in keys},
            "touched": list(p["touched"]),
            "started_at": p["at"],
            "ended_at": None if p["status"] == "running" else p["at"],
        }
        return [{"review": p["review"], "n": p["n"]}]

    def _w_finish_step(self, p: Mapping[str, Any]) -> list[Row]:
        s = self.steps.get((p["review"], p["n"]))
        if s is None or s["status"] != "running":
            return []
        s.update(status=p["status"], count=p["count"], error=p["error"],
                 touched=list(p["touched"]), ended_at=p["at"])  # fmt: skip
        return [{"review": s["review"], "n": s["n"], "status": s["status"]}]

    def _r_review_steps(self, p: Mapping[str, Any]) -> list[Row]:
        wanted = set(p["reviews"])
        rows = sorted((s for (r, _), s in self.steps.items() if r in wanted),
                      key=lambda s: (s["review"], s["n"]))  # fmt: skip
        return [ReviewStep(**s).model_dump() for s in rows]

    # --- consults -----------------------------------------------------------------------------

    def _w_post_consult(self, p: Mapping[str, Any]) -> list[Row]:
        uid = consult_uid(p["gap"], p["role"], p["attempt"], p["archive"])
        created = uid not in self.consults
        if created:
            self.consults[uid] = Consult(uid=uid, gap=p["gap"], role=p["role"],
                                         attempt=p["attempt"], archive=p["archive"],
                                         created_at=p["now"])  # fmt: skip
        return [{"uid": uid, "created": created}]

    def _r_queue_consult(self, p: Mapping[str, Any]) -> list[Row]:
        rows = [c for c in self.consults.values() if c.role == p["role"] and c.status == "open"]
        rows.sort(key=lambda c: (c.created_at, c.uid))
        return [c.model_dump() for c in rows]

    def _w_answer_consult(self, p: Mapping[str, Any]) -> list[Row]:
        c = self.consults.get(p["consult"])
        if c is None or c.status != "open":
            return []
        answer = {k: p[k] for k in ("can_ground", "kind", "subject", "statement", "value")}
        self.consults[c.uid] = Consult(
            **{
                **c.model_dump(),
                **answer,
                "status": "answered",
                "cites": list(p["cites"]),
                "answered_at": p["now"],
            }
        )
        return [{"uid": c.uid, "status": "answered"}]

    def _r_consults_for_gap(self, p: Mapping[str, Any]) -> list[Row]:
        gap = self.gaps.get(p["gap"])
        if gap is None:
            return []
        rows = sorted(
            (
                c
                for c in self.consults.values()
                if c.gap == gap.uid and c.attempt == gap.attempts and c.archive == gap.archive_asked
            ),
            key=lambda c: c.role,
        )
        return [c.model_dump() for c in rows]

    # --- claims -------------------------------------------------------------------------------

    def _w_write_claim(self, p: Mapping[str, Any]) -> list[Row]:
        if p["uid"] in self.claims:
            return []
        c = Claim(**{k: p[k] for k in Claim.model_fields})
        self.claims[c.uid] = c
        return [{"uid": c.uid}]

    def _r_get_claim(self, p: Mapping[str, Any]) -> list[Row]:
        c = self.claims.get(p["uid"])
        return [c.model_dump()] if c else []

    @staticmethod
    def _newest(claims: list[Claim]) -> list[Claim]:
        return sorted(claims, key=lambda c: (c.updated_at, c.uid), reverse=True)

    def _r_claims(self, p: Mapping[str, Any]) -> list[Row]:
        rows = self._newest([c for c in self.claims.values() if c.status in p["statuses"]])
        return [c.model_dump() for c in rows[: p["limit"]]]

    def _r_claims_for_subject(self, p: Mapping[str, Any]) -> list[Row]:
        rows = self._newest(
            [
                c
                for c in self.claims.values()
                if (c.kind, c.subject) == (p["kind"], p["subject"]) and c.status in p["statuses"]
            ]
        )
        return [c.model_dump() for c in rows]

    def _r_claims_for_gap(self, p: Mapping[str, Any]) -> list[Row]:
        rows = self._newest(
            [c for c in self.claims.values() if c.gap == p["gap"] and c.status in p["statuses"]]
        )
        return [c.model_dump() for c in rows]

    def _w_set_claim_status(self, p: Mapping[str, Any]) -> list[Row]:
        c = self.claims.get(p["uid"])
        if c is None or c.status not in p["from"]:
            return []
        to = p["to"]
        c.status = to
        c.updated_at = p["now"]
        if to == "accepted" and c.valid_from is None:
            c.valid_from = p["now"]
        if to in ("accepted", "rejected") and p["by"] is not None:
            c.approved_by = p["by"]
        if to == "pending_approval":  # an accept undone: not approved, not valid
            c.approved_by = c.valid_from = None
        if p["why"] is not None:
            c.why = p["why"]
        if p["valid_to"] is not None:
            c.valid_to = p["valid_to"]
        if p["conflict"] is not None:
            c.conflict = p["conflict"]
        return [{"uid": c.uid, "status": c.status}]

    # --- follow-ups ---------------------------------------------------------------------------

    def _w_open_followup(self, p: Mapping[str, Any]) -> list[Row]:
        uid = followup_uid(p["claim"])
        created = uid not in self.followups
        if created:
            self.followups[uid] = FollowUp(
                uid=uid,
                claim=p["claim"],
                title=p["title"],
                body=p["body"],
                by=p["by"],
                created_at=p["now"],
            )
        return [{"uid": uid, "created": created}]

    def _w_follow_up_tried(self, p: Mapping[str, Any]) -> list[Row]:
        c = self.claims.get(p["claim"])
        if c is None or c.follow_up_tries:
            return []
        c.follow_up_tries = 1
        return [{"uid": c.uid, "follow_up_tries": c.follow_up_tries}]

    def _r_queue_follow_up(self, p: Mapping[str, Any]) -> list[Row]:
        done = {f.claim for f in self.followups.values()}
        rows = [
            c
            for c in self.claims.values()
            if c.uid not in done
            and not c.follow_up_tries
            and (
                (c.status == "accepted" and c.kind in ("owner", "expert", "decision"))
                or c.status == "conflicts_with_source"
            )
        ]
        rows.sort(key=lambda c: (c.updated_at, c.uid))
        return [c.model_dump() for c in rows]

    def _r_followups(self, p: Mapping[str, Any]) -> list[Row]:
        rows = [f for f in self.followups.values() if p["status"] in (None, f.status)]
        rows.sort(key=lambda f: (f.created_at, f.uid), reverse=True)
        return [f.model_dump() for f in rows[: p["limit"]]]

    # --- archive requests ---------------------------------------------------------------------

    def _w_archive_open_request(self, p: Mapping[str, Any]) -> list[Row]:
        live = sorted(
            (r for r in self.requests.values() if r.norm == p["norm"] and r.status in LIVE_REQUEST),
            key=lambda r: (r.created_at, r.uid),
        )
        if live:
            return [{"uid": live[0].uid, "created": False, "status": live[0].status}]
        r = ArchiveRequest(
            uid=p["uid"],
            kind=p["kind"],
            text=p["text"],
            refs=list(p["refs"]),
            from_uid=p["from_uid"],
            asked_by=p["asked_by"],
            gap=p["gap"],
            thread=p["thread"],
            norm=p["norm"],
            created_at=p["now"],
            updated_at=p["now"],
        )
        self.requests[r.uid] = r
        return [{"uid": r.uid, "created": True, "status": r.status}]

    def _r_archive_get_request(self, p: Mapping[str, Any]) -> list[Row]:
        r = self.requests.get(p["uid"])
        return [r.model_dump()] if r else []

    def _r_archive_queue(self, p: Mapping[str, Any]) -> list[Row]:
        rows = sorted(
            (r for r in self.requests.values() if r.status == "open"),
            key=lambda r: (r.created_at, r.uid),
        )
        return [r.model_dump() for r in rows[: p["limit"]]]

    def _w_archive_set_request(self, p: Mapping[str, Any]) -> list[Row]:
        r = self.requests.get(p["uid"])
        if r is None or r.status not in p["from"]:
            return []
        r.status = p["to"]
        r.outcome, r.summary, r.reason = p["outcome"], p["summary"], p["reason"]
        r.partial, r.calls, r.updated_at = p["partial"], p["calls"], p["now"]
        return [{"uid": r.uid, "status": r.status}]

    def _w_archive_write_find(self, p: Mapping[str, Any]) -> list[Row]:
        if p["request"] not in self.requests:
            return []
        f = ArchiveFind(**{k: p[k] for k in ArchiveFind.model_fields})
        self.finds[(f.request, f.uid)] = f
        return [{"request": f.request, "uid": f.uid}]

    def _r_archive_finds(self, p: Mapping[str, Any]) -> list[Row]:
        keys = sorted(k for k in self.finds if k[0] in p["requests"])
        return [self.finds[k].model_dump() for k in keys]

    def _r_archive_recall(self, p: Mapping[str, Any]) -> list[Row]:
        rows = [
            r
            for r in self.requests.values()
            if r.norm == p["norm"]
            and r.status == "answered"
            and not r.partial
            and r.updated_at >= p["since"]
            and not (
                p["asked_by"] == "keeper" and (r.asked_by, r.outcome) == ("ask", "nothing_found")
            )
        ]
        rows.sort(key=lambda r: (r.updated_at, r.uid), reverse=True)
        return [r.model_dump() for r in rows[:1]]

    def _r_archive_requests(self, p: Mapping[str, Any]) -> list[Row]:
        rows = [r for r in self.requests.values() if r.status in p["statuses"]]
        rows.sort(key=lambda r: (r.updated_at, r.uid), reverse=True)
        return [r.model_dump() for r in rows[: p["limit"]]]

    def _r_archive_requests_for_gap(self, p: Mapping[str, Any]) -> list[Row]:
        rows = [r for r in self.requests.values() if r.gap == p["gap"]]
        rows.sort(key=lambda r: (r.updated_at, r.uid), reverse=True)
        return [r.model_dump() for r in rows]
