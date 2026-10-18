"""Run the Archivist on one request: `answer_request`, the one way its job runs.

    recall (rule 15: answered lately -> that answer, no run)
    -> refuse: the company is building (19), a ref no source owns (2), the daily cap (10)
    -> open -> running (before any model call: a review's queue never takes a running request)
    -> run_job (role prompt, read tools + archive tools on one ArchiveSession, the tier's
       budgets, `archivist_steps` steps) -> the role's apply (checks, load, finds, log)
    -> what the run left: refused (a source refused), failed (a source kept failing, or no
       answer), or answered + partial (stopped, step limit). Past the soft deadline (`wrap_up`)
       the source tools ask for the submit, so the run still ends in apply.

Every tool call and the submit are written as `ReviewStep`s under the request's uid (actor
"archivist"), as a Keeper review writes its jobs' steps, so the run can be shown step by step.
Never raises: an error ends the request `failed` with the reason.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
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
from agents.keeper.steps import StepTrail
from agents.roles.archivist import ACTOR, ROLE, ArchiveRun
from agents.roles.base import Ctx, Subject, write
from agents.roles.keeper import log
from agents.runner import STOPPED, role_toolset, run_job
from agents.toolset import Runner, Toolset
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
    wrap_up: Callable[[], bool] | None = None,
) -> ArchiveRequest:
    """Answer one open request; returns it as the ledger holds it afterwards. `should_stop` is
    the hard stop (nothing is applied); once `wrap_up()` is true the source tools refuse and
    ask for the submit, so what was fetched is still checked and loaded (rule 8)."""
    ctx = Ctx(f"agent:{ACTOR}", ROLE.db_user, utc_now())  # type: ignore[arg-type]
    hooks = _Hooks(on_event, should_stop, wrap_up, graph_run)
    try:
        _answer(store, slug, request, ctx, client, tier, hooks, backends, building or _never)
        return _get(store, request.uid) or request
    except Exception as e:  # never raised: the request records why it failed
        _log.warning("archive request %s failed", request.uid, exc_info=True)
        reason = f"error: {type(e).__name__}: {e}"[:300]
        try:
            _end(store, ctx, request, "failed", reason=reason, frm=["open", "running"])
            return _get(store, request.uid) or request
        except Exception:  # the ledger itself is down: say so without it
            _log.warning("could not record the failure of %s", request.uid, exc_info=True)
            return request.model_copy(update={"status": "failed", "reason": reason})


@dataclass(frozen=True)
class _Hooks:
    """The caller's ways into a run."""

    on_event: Callable[[dict[str, Any]], None] | None
    should_stop: Callable[[], bool] | None
    wrap_up: Callable[[], bool] | None
    graph_run: Runner | None


def _answer(
    store: WorkStore,
    slug: str,
    request: ArchiveRequest,
    ctx: Ctx,
    client: anthropic.Anthropic,
    tier: Tier,
    hooks: _Hooks,
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
        _run(store, request, ctx, session, client, hooks)
    finally:
        session.close()


def _run(
    store: WorkStore,
    request: ArchiveRequest,
    ctx: Ctx,
    session: ArchiveSession,
    client: anthropic.Anthropic,
    hooks: _Hooks,
) -> None:
    trouble = Trouble()
    run = ArchiveRun(request, session, trouble)
    trail = StepTrail(store, request.uid, ROLE.db_user)
    tools = archive_toolset(session, role_toolset(ROLE, hooks.graph_run), trouble=trouble,
                            wrap_up=hooks.wrap_up)  # fmt: skip
    job = replace(JOB, apply=partial(JOB.apply, run=run), context=partial(JOB.context, run=run))

    def stop() -> bool:
        return trouble.halt or (hooks.should_stop is not None and hooks.should_stop())

    result = run_job(
        store, ROLE, job, Subject("archive_request", request.uid, request.model_dump()), ctx,
        client=client, toolset=Toolset(tools.tools, trail.wrap(tools.run, ACTOR)),
        on_event=hooks.on_event, should_stop=stop, recursion_limit=get_settings().archivist_steps,
    )  # fmt: skip
    if result.submitted or result.rows:  # no submit step for a run that never tried one
        submit = result.submit or {}
        shown = {k: submit[k] for k in ("outcome", "summary") if k in submit}
        shown["finds"] = [f.get("uid") for f in submit.get("finds", [])]
        trail.submit_step(ACTOR, JOB.submit.name, shown, result)
    if result.rows:
        return  # apply answered it
    calls = session.calls_used
    if trouble.refused:
        _refuse(store, ctx, request, f"refused: {trouble.refused}", frm=["running"], calls=calls)
    elif trouble.failed:
        _end(store, ctx, request, "failed", reason=trouble.failed, calls=calls)
    elif result.stop in (STOPPED, "step_limit"):
        summary = "Stopped before it reported anything."
        log(store, ctx, ACTOR, "archive_nothing", gap=request.gap,
            why=f"{request.uid}: {summary}")  # fmt: skip
        _end(store, ctx, request, "answered", outcome="nothing_found", summary=summary,
             reason=result.stop, partial=True, calls=calls)  # fmt: skip
    elif result.submit is None and not (result.stop or "").startswith("error"):
        _end(store, ctx, request, "failed", reason="no_answer", calls=calls)
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
