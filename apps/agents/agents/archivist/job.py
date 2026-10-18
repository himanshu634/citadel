"""Run the Archivist on one request: `answer_request`, the one way its job runs.

    recall (rule 15: answered lately -> that answer, no run)
    -> refuse: the company is building (19), a ref no source owns (2), the daily cap (10)
    -> open -> running (before any model call: a review's queue never takes a running request)
    -> run_job (role prompt, read tools + archive tools on one ArchiveSession, the tier's
       budgets, `archivist_steps` steps) -> the role's apply (checks, load, finds, log)
    -> what the run left: refused (a source refused), failed (a source kept failing, or no
       answer), or answered + partial (stopped, step limit)

Every tool call and the submit are written as `ReviewStep`s under the request's uid (actor
"archivist"), as a Keeper review writes its jobs' steps, so the run can be shown step by step.
Never raises: an error ends the request `failed` with the reason.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from typing import Any, Literal

import anthropic
from brain.archive.session import ArchiveSession, Budget, daily_loaded
from brain.config import get_settings

from agents.archivist import rules
from agents.archivist.tools import Trouble, archive_toolset
from agents.keeper.gaps import utc_now
from agents.keeper.model import ArchiveRequest
from agents.roles.archivist import ACTOR, ROLE, ArchiveRun
from agents.roles.base import Ctx, Subject, write
from agents.roles.keeper import log
from agents.runner import STOPPED, RunResult, role_toolset, run_job
from agents.toolset import Runner, Toolset
from agents.walk import subgraph
from agents.work.store import WorkStore

_log = logging.getLogger(__name__)

Tier = Literal["ask", "keeper"]
JOB = ROLE.job("answer_request")


def _never(slug: str) -> bool:
    return False


def answer_request(
    store: WorkStore,
    slug: str,
    request: ArchiveRequest,
    *,
    client: anthropic.Anthropic,
    tier: Tier,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    graph_run: Runner | None = None,
    backends: Mapping[str, Any] | None = None,
    building: Callable[[str], bool] | None = None,
) -> ArchiveRequest:
    """Answer one open request; returns it as the ledger holds it afterwards."""
    ctx = Ctx(f"agent:{ACTOR}", ROLE.db_user, utc_now())  # type: ignore[arg-type]
    try:
        _answer(store, slug, request, ctx, client, tier, on_event, should_stop, graph_run,
                backends, building or _never)  # fmt: skip
    except Exception as e:  # never raised: the request records why it failed
        _log.warning("archive request %s failed", request.uid, exc_info=True)
        _end(store, ctx, request, "failed", reason=f"error: {type(e).__name__}: {e}"[:300],
             frm=["open", "running"])  # fmt: skip
    return _get(store, request.uid) or request


def _answer(
    store: WorkStore,
    slug: str,
    request: ArchiveRequest,
    ctx: Ctx,
    client: anthropic.Anthropic,
    tier: Tier,
    on_event: Callable[[dict[str, Any]], None] | None,
    should_stop: Callable[[], bool] | None,
    graph_run: Runner | None,
    backends: Mapping[str, Any] | None,
    building: Callable[[str], bool],
) -> None:
    if earlier := rules.recall(store, request.norm, tier, datetime.now(UTC)):
        _from_memory(store, ctx, request, earlier)
        return
    if building(slug):
        _refuse(store, ctx, request, "building")
        return
    sources = None if backends is None else dict(backends)  # None: the company's own
    session = ArchiveSession(slug, Budget.for_tier(tier), backends=sources, start_refs=request.refs)
    try:
        reason = rules.check_scope(request.refs, session.backends)
        if reason is None and daily_loaded(slug, datetime.now(UTC).date()) >= (
            get_settings().archivist_daily_cap
        ):
            reason = "daily_cap"
        if reason:
            _refuse(store, ctx, request, reason)
            return
        if not _set(store, ctx, request, ["open"], "running"):
            return  # another run has it (rule 16): the caller reads it as it is
        _run(store, slug, request, ctx, session, client, on_event, should_stop, graph_run)
    finally:
        session.close()


def _run(
    store: WorkStore,
    slug: str,
    request: ArchiveRequest,
    ctx: Ctx,
    session: ArchiveSession,
    client: anthropic.Anthropic,
    on_event: Callable[[dict[str, Any]], None] | None,
    should_stop: Callable[[], bool] | None,
    graph_run: Runner | None,
) -> None:
    trouble = Trouble()
    run = ArchiveRun(request, session, trouble)
    steps = _Steps(store, request.uid)
    tools = archive_toolset(session, role_toolset(ROLE, graph_run), trouble=trouble)
    job = replace(JOB, apply=partial(JOB.apply, run=run), context=partial(JOB.context, run=run))

    def stop() -> bool:
        return trouble.halt or (should_stop is not None and should_stop())

    result = run_job(
        store, ROLE, job, Subject("archive_request", request.uid, request.model_dump()), ctx,
        client=client, toolset=steps.tracked(tools), on_event=on_event, should_stop=stop,
        recursion_limit=get_settings().archivist_steps,
    )  # fmt: skip
    steps.submit(JOB.submit.name, result)
    if result.rows:
        return  # apply answered it
    calls = session.calls_used
    if trouble.refused:
        _refuse(store, ctx, request, f"refused: {trouble.refused}", frm=["running"], calls=calls)
    elif trouble.failed:
        _end(store, ctx, request, "failed", reason=trouble.failed, calls=calls)
    elif result.stop in (STOPPED, "step_limit"):
        summary = "Stopped before it reported anything."
        log(store, ctx, ACTOR, "archive_nothing", gap=request.gap, why=f"{request.uid}: {summary}")
        _end(store, ctx, request, "answered", outcome="nothing_found", summary=summary,
             reason=result.stop, partial=True, calls=calls)  # fmt: skip
    else:
        _end(store, ctx, request, "failed", reason=result.stop or "no_answer", calls=calls)


# --- ledger writes ----------------------------------------------------------------------------


def _get(store: WorkStore, uid: str) -> ArchiveRequest | None:
    rows = store.read("ledger/archive_get_request", {"uid": uid})
    return ArchiveRequest(**rows[0]) if rows else None


def _set(
    store: WorkStore, ctx: Ctx, request: ArchiveRequest, frm: list[str], to: str, **fields: Any
) -> bool:
    """A guarded status move; False when the request was no longer in `frm`."""
    return bool(write(store, ctx, "ledger/archive_set_request", uid=request.uid, to=to,
                      **{"from": frm}, **fields))  # fmt: skip


def _end(
    store: WorkStore,
    ctx: Ctx,
    request: ArchiveRequest,
    to: str,
    *,
    frm: list[str] | None = None,
    **fields: Any,
) -> None:
    _set(store, ctx, request, frm or ["running"], to, **fields)


def _refuse(
    store: WorkStore,
    ctx: Ctx,
    request: ArchiveRequest,
    reason: str,
    *,
    frm: list[str] | None = None,
    calls: int = 0,
) -> None:
    if _set(store, ctx, request, frm or ["open"], "refused", reason=reason, calls=calls):
        log(store, ctx, ACTOR, "archive_refused", gap=request.gap, why=f"{request.uid}: {reason}")


def _from_memory(
    store: WorkStore, ctx: Ctx, request: ArchiveRequest, earlier: ArchiveRequest
) -> None:
    """Rule 15: the earlier answer and its finds, recorded on this request, with no run."""
    if not _set(store, ctx, request, ["open"], "answered", outcome=earlier.outcome,
                summary=earlier.summary, reason=f"from memory: {earlier.uid}"):  # fmt: skip
        return
    loaded = []
    for f in store.read("ledger/archive_finds", {"requests": [earlier.uid]}):
        write(store, ctx, "ledger/archive_write_find", **{**f, "request": request.uid})
        loaded.append(f["uid"])
    action = "archive_loaded" if loaded else "archive_nothing"
    log(store, ctx, ACTOR, action, gap=request.gap, evidence=loaded,
        why=f"{request.uid}: from memory ({earlier.uid}): {earlier.summary}")  # fmt: skip


# --- steps ------------------------------------------------------------------------------------


class _Steps:
    """The run's steps on the ledger under the request's uid: each tool call `running` then
    `done` / `failed`, then the submit. Best effort: a step write never changes the run."""

    def __init__(self, store: WorkStore, review: str) -> None:
        self.store = store
        self.review = review
        self._n = 0
        self._lock = threading.Lock()

    def tracked(self, tools: Toolset) -> Toolset:
        base = tools.run

        def run(slug: str, name: str, **params: Any) -> list[Any]:
            n = self.step(name, "graph", params, "running")
            try:
                rows = base(slug, name, **params)
            except Exception as e:
                self.finish(n, "failed", error=f"{type(e).__name__}: {e}"[:300])
                raise
            self.finish(n, "done", count=len(rows), touched=_touched(name, params, rows))
            return rows

        return Toolset(tools=tools.tools, run=run)

    def submit(self, tool: str, result: RunResult) -> None:
        summary = {
            k: result.submit[k] for k in ("outcome", "summary") if k in (result.submit or {})
        }
        summary["finds"] = [f.get("uid") for f in (result.submit or {}).get("finds", [])]
        status = "done" if result.rows else "failed"
        self.step(tool, "submit", summary, status,
                  error=None if result.rows else (result.stop or "no_write"))  # fmt: skip

    def step(self, tool: str, kind: str, params: dict[str, Any], status: str, **ended: Any) -> int:
        with self._lock:
            self._n += 1
            n = self._n
        row = {"review": self.review, "n": n, "actor": ACTOR, "tool": tool, "kind": kind,
               "input": json.dumps(params, default=str, ensure_ascii=False), "status": status,
               "at": utc_now(), **ended}  # fmt: skip
        self._write("ledger/write_step", row)
        return n

    def finish(self, n: int, status: str, **ended: Any) -> None:
        row = {"review": self.review, "n": n, "status": status, "at": utc_now(), **ended}
        self._write("ledger/finish_step", row)

    def _write(self, name: str, row: dict[str, Any]) -> None:
        try:
            self.store.write(name, ROLE.db_user, row)
        except Exception:  # best effort: the trail must never change the run
            _log.warning("could not write a step of %s", self.review, exc_info=True)


def _touched(name: str, params: dict[str, Any], rows: list[Any]) -> list[str]:
    """The brain uids a call touched (archive tools touch none: their items are not loaded)."""
    try:
        data = [r.model_dump(mode="json", by_alias=True) if hasattr(r, "model_dump") else r
                for r in rows]  # fmt: skip
        nodes, _ = subgraph(name, params, data)
        return list(dict.fromkeys(nd["uid"] for nd in nodes if nd.get("uid")))
    except Exception:
        return []
