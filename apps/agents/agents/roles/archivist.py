"""Archivist agent: finds items older than the ingest window for one archive request, checks
them against the brain, and loads the ones it can stand behind (spec: "The Archivist").

One job, `answer_request`, on the Keeper's ledger. Its tools are the read tools below plus the
source tools of `agents.archivist.tools`, which only `agents.archivist.job.answer_request`
builds (they need the request's `ArchiveSession`); so the job runs through it, which binds the
run (`ArchiveRun`) into `context` and `apply`.

`apply` is fixed code (spec rules 12-14, 3b): each find is checked (`rules.check_find`), a
failing one is dropped and logged with its reason, the rest are loaded (`session.load`, within
the items budget and the daily cap, with their supersession), and only what loaded is recorded
as an `ArchiveFind`. A `conflicts` verdict opens a Keeper gap (`archive_conflict`). The outcome
follows what loaded, never just what the model said.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from brain.archive.session import ArchiveSession, BudgetSpent

from agents.archivist import rules
from agents.archivist.tools import Trouble
from agents.keeper.model import ArchiveRequest, gap_uid, iso
from agents.roles.base import Ctx, Job, Role, Subject, write
from agents.roles.keeper import log
from agents.work.store import Row, WorkStore
from agents.work.submits import FindIn, SubmitArchiveAnswer

_log = logging.getLogger(__name__)

ACTOR = "archivist"
QUEUE_LIMIT = 20  # open requests read per queue pass

_REQUEST_KEYS = ("uid", "kind", "text", "refs", "from_uid", "asked_by")


@dataclass
class ArchiveRun:
    """What one run of the job works with besides the ledger: the request, its session (the
    sources and budgets) and what went wrong at the sources."""

    request: ArchiveRequest
    session: ArchiveSession
    trouble: Trouble


def queue(store: WorkStore, ctx: Ctx) -> list[Subject]:
    """Open requests, oldest first."""
    rows = store.read("ledger/archive_queue", {"limit": QUEUE_LIMIT})
    return [Subject("archive_request", r["uid"], r) for r in rows]


def context(store: WorkStore, ctx: Ctx, s: Subject, run: ArchiveRun | None = None) -> dict:
    """The request, the source keys to search and fetch from, and the budget."""
    out: dict[str, Any] = {"request": {k: s.data.get(k) for k in _REQUEST_KEYS}}
    if run is not None:
        out["sources"] = sorted(run.session.backends)
        out["budget"] = asdict(run.session.budget)
    return out


def _why(request: ArchiveRequest, text: str) -> str:
    return f"{request.uid}: {text}"


def apply(
    store: WorkStore,
    ctx: Ctx,
    s: Subject,
    sub: SubmitArchiveAnswer,
    run: ArchiveRun | None = None,
) -> list[Row]:
    if run is None:
        raise ValueError("the answer_request job runs through agents.archivist.job.answer_request")
    request, session = run.request, run.session
    resolve = rules.resolver(session.backends)
    kept, dropped = [], []
    for f in {f.uid: f for f in sub.finds}.values():
        reason = rules.check_find(f, session.fetched.get(f.uid), request, session.lookup,
                                  ids=session.ids_for(f.uid), resolve=resolve)  # fmt: skip
        if reason:
            dropped.append(reason)
            log(store, ctx, ACTOR, "archive_dropped", gap=request.gap,
                why=_why(request, f"{f.uid} dropped: {reason}"))  # fmt: skip
        else:
            kept.append(f)

    superseded = {f.uid: f.superseded_by for f in kept if f.superseded_by}
    loaded: list[str] = []
    no_room = None
    if kept:
        try:
            loaded = session.load(request.uid, [f.uid for f in kept], superseded=superseded)
        except BudgetSpent as e:  # no room at all: items or the daily cap
            run.trouble.spent.add(e.budget)
            no_room = f"Nothing could be loaded: the {e.budget} budget is spent."

    rows: list[Row] = []
    for f in (f for f in kept if f.uid in loaded):
        # The item is loaded: recording it is best effort, so one failed write never loses the
        # others or the answer.
        try:
            rows += _record(store, ctx, request, f, session)
        except Exception:
            _log.warning("could not record find %s of %s", f.uid, request.uid, exc_info=True)

    if loaded:
        outcome, summary = "found", sub.summary
        if len(loaded) < len(kept):
            summary += f" Loaded {len(loaded)} of {len(kept)}; the rest hit a budget."
    elif sub.outcome == "already_in_brain":
        outcome, summary = "already_in_brain", sub.summary
    else:
        outcome = "nothing_found"
        summary = no_room or (f"Nothing could be loaded: {dropped[0]}" if dropped else sub.summary)
    partial = len(loaded) < len(kept) or run.trouble.partial
    action = "archive_loaded" if loaded else "archive_nothing"
    log(store, ctx, ACTOR, action, gap=request.gap, why=_why(request, summary), evidence=loaded)
    rows += write(
        store, ctx, "ledger/archive_set_request", uid=request.uid, to="answered", outcome=outcome,
        summary=summary, partial=partial, calls=session.calls_used, **{"from": ["running"]},
    )  # fmt: skip
    return rows


def _record(
    store: WorkStore, ctx: Ctx, request: ArchiveRequest, f: FindIn, session: ArchiveSession
) -> list[Row]:
    """One loaded find on the ledger, and its conflict gap when it conflicts."""
    c = session.fetched[f.uid].candidate
    rows = write(
        store, ctx, "ledger/archive_write_find", request=request.uid, uid=f.uid, url=c.url,
        title=c.title, date=iso(c.date.timestamp()) if c.date else None, why=f.why,
        quote=f.quote, verdict=f.verdict, evidence=f.evidence, superseded_by=f.superseded_by,
    )  # fmt: skip
    if f.verdict == "conflicts":
        try:
            _conflict(store, ctx, request, f.uid, c.title, f.why, f.evidence)
        except Exception:
            _log.warning("could not open the conflict gap of %s", f.uid, exc_info=True)
    return rows


def _conflict(
    store: WorkStore,
    ctx: Ctx,
    request: ArchiveRequest,
    uid: str,
    title: str,
    why: str,
    evidence: list[str],
) -> None:
    """3b: an archived item that disagrees with a Keeper claim or a declared owner opens a gap
    about it (deduped on the item), for a review to settle."""
    [row] = write(
        store, ctx, "ledger/open_gap", uid=gap_uid(), kind="archive_conflict",
        text=f"An archived item conflicts with the brain: {title}. {why}",
        norm=f"archive_conflict {uid}", subject=uid, about=[uid, *evidence],
    )  # fmt: skip
    log(store, ctx, ACTOR, "archive_conflict", gap=row["uid"],
        why=_why(request, f"{uid} conflicts: {why}"), evidence=evidence)  # fmt: skip


ROLE = Role(
    name="archivist",
    db_user="citadel_archivist",
    read_tools=(
        "get_entity",
        "keeper_notes",
        "list_systems",
        "related_documents",
        "related_work_items",
        "semantic_search",
    ),
    jobs=(Job("answer_request", SubmitArchiveAnswer, queue, apply, context),),
    summary="Finds items older than the ingest window, checks them against the brain, loads them.",
)
