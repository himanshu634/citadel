"""The Keeper's review run: one bounded pass over the ledger, started after a build, by Review
now, or after an approval (docs/superpowers/specs/2026-10-16-keeper-design.md, "The review run",
"Running it").

    1. start      `ledger/review_start`; a review already running is returned, nothing starts
    2. reproject  every accepted claim against the new sources (`project.reproject`), then
       notice     open gaps the brain shows on its own (`notice.notice`, cap keeper_notice_cap)
    3. pick       `budget` open gaps (`rules.pick_order`) -> in_review
    4. consult    post a pm and a qa consult per picked gap (attempt = gap.attempts), then run
                  those roles' consult jobs on them
    5. decide     the keeper's decide job on each picked gap whose consults are answered
    6. follow up  pm's follow_up job, once per claim in its queue (not budgeted); a run that
                  opens no task is recorded, and the claim is not tried again
    7. finish     `ledger/review_finish("done")`

`budget=0` runs only 1, 2, 6 and 7 (the backend's run after an approval, so the follow-up shows).
Every job goes through `runner.run_job` with `client_for(role, job)`: `llm.client()` in
production, `policies.offline_client` offline.

The run ends early, between jobs:
- `should_stop()` -> `stopped`, stop "requested". Asked while a job runs, that job's writes are
  refused too (a rebuild stops the review before it empties brain_<slug>).
- brain_<slug> missing (`graph_exists` False, `BrainUnavailable`) or a FalkorDB `ResponseError`
  -> `stopped`, stop "brain_unavailable". `run_job` catches a job's errors, so the jobs' writes
  are wrapped to pass these two through.
- anything else -> `failed`, its message in `stop`.

Steps (the Systems page's activity trail, `agents/activity.py`): every graph-tool call a pm, qa or
keeper job makes is written to the ledger as a `ReviewStep` (`ledger/write_step`) `running` when
it starts and finished (`ledger/finish_step`) `done` or `failed`, with its row count and the brain
uids it touched (`agents.walk.subgraph`); each job then adds one `submit` step, `failed` when it
wrote nothing. The pick records the picked gaps and the first one's text on the Review
(`ledger/review_picked`). Step writes are best effort: a ledger hiccup never changes a job.

Whatever the end, the gaps this run moved to in_review and left undecided (still in_review, no
claim waiting for a lead) go back to `open` without using an attempt, so the next review can
pick them; a run first does the same for gaps an earlier run left behind (a killed process).
Each is logged `gap_released`. Every job's writes are refused when brain_<slug> is gone: the loop
turns graph-tool errors into tool results, so such a run would record "nothing found". Every step
emits a `ReviewEvent`; every end, even an unexpected one, finishes the review and writes the
LogEntry `review_<state>`.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol

from brain.config import get_settings
from redis.exceptions import ResponseError

from agents.keeper import decide
from agents.keeper.decide import (
    DB_USER,
    BrainFacts,
    BrainUnavailable,
    _set_gap,
    brain_present,
    log,
)
from agents.keeper.gaps import utc_now
from agents.keeper.model import Gap, Review, review_uid
from agents.keeper.notice import notice
from agents.keeper.project import reproject
from agents.keeper.rules import pick_order
from agents.roles import ROLES
from agents.roles.base import Ctx, Job, Subject
from agents.runner import RunResult, run_job
from agents.toolset import Runner
from agents.walk import subgraph
from agents.work.store import WorkStore

_log = logging.getLogger(__name__)

GAP_LIMIT = 10_000  # open gaps read for picking (pick_order needs all of them)
CONSULTED_BY = ("pm", "qa")
REQUESTED = "requested"  # stop: should_stop() said so
BRAIN_UNAVAILABLE = "brain_unavailable"  # stop: brain_<slug> is gone or FalkorDB refused
NO_API_KEY = "no_api_key"  # stop of a skipped review: no key for the LLM jobs
SUBMIT_KEYS = ("can_ground", "outcome", "kind", "title")  # a submit step's input, when present

EventKind = Literal["start", "step", "done", "stopped", "failed", "skipped"]


@dataclass(frozen=True)
class ReviewEvent:
    """One progress event of a review run, for the stream the app shows."""

    kind: EventKind
    step: str | None = None  # reproject, notice, pick, consult, pm.consult, keeper.decide, ...
    gap: str | None = None
    claim: str | None = None
    message: str = ""


class ReviewBrain(BrainFacts, Protocol):
    """What the review run needs of brain_<slug>: the decide step's facts, plus noticing."""

    def notice(self, slug: str, kind: str, limit: int) -> list[dict[str, Any]]: ...


class _Stop(Exception):
    """End the run early: `stopped`, with this stop reason."""


def review(
    store: WorkStore,
    slug: str,
    *,
    budget: int,
    trigger: Literal["build", "manual", "approval"],
    client_for: Callable[[str, str], Any],
    graph_run: Runner | None = None,
    brain: ReviewBrain | None = None,
    on_event: Callable[[ReviewEvent], None] = lambda e: None,
    should_stop: Callable[[], bool] = lambda: False,
    now: Callable[[], str] = utc_now,
    uid: str | None = None,
) -> Review:
    """Run one review (see the module doc). Returns the review as it ended, or the running one
    when a review is already running. `brain` defaults to `decide.DEFAULT_BRAIN`, read now.
    `uid` (default: a new one) lets the caller know the review before it starts."""
    uid, started = uid or review_uid(), now()
    start = {"uid": uid, "trigger": trigger, "budget": budget, "now": started}
    if not store.write("ledger/review_start", DB_USER, start):
        [current] = store.read("ledger/review_current", {})
        return Review(**current)

    run: _Run | None = None
    state: Literal["done", "stopped", "failed"] = "failed"
    stop: str | None = "interrupted"  # an end the handlers below did not see (e.g. Ctrl-C)
    message = "Review failed: interrupted."
    try:
        try:
            run = _Run(store, slug, brain or decide.DEFAULT_BRAIN, client_for, graph_run,
                       on_event, should_stop, now, uid)  # fmt: skip
            log(store, started, "keeper", "review_start", why=f"{uid}: {trigger}, budget {budget}")
            on_event(ReviewEvent("start", message=f"Review started ({trigger}, budget {budget})."))
            run.steps(budget)
            state, stop, message = "done", None, "Review done."
        except _Stop as e:
            state, stop, message = "stopped", str(e), "Review stopped on request."
        except (BrainUnavailable, ResponseError) as e:
            state, stop = "stopped", BRAIN_UNAVAILABLE
            message = f"Review stopped: the brain is unavailable ({type(e).__name__}: {e})."
        except Exception as e:  # any other failure ends the run as failed, with its message
            state, stop = "failed", f"{type(e).__name__}: {e}"[:300]
            message = f"Review failed: {stop}"
        if run is not None:
            try:
                run.release(f"{uid} {state} before deciding it")
            except Exception as e:  # the ledger refused: still finish the review
                if state == "done":
                    state, stop = "failed", f"release: {type(e).__name__}: {e}"[:300]
                    message = f"Review failed: {stop}"
    finally:  # whatever happened above, the review does not stay `running`
        ended = now()
        store.write("ledger/review_finish", DB_USER,
                    {"uid": uid, "state": state, "stop": stop, "now": ended})  # fmt: skip
        log(store, ended, "keeper", f"review_{state}", why=f"{uid}: {stop or state}")
    on_event(ReviewEvent(state, message=message))
    return Review(uid=uid, slug=slug, trigger=trigger, state=state, budget=budget,
                  started_at=started, ended_at=ended, stop=stop)  # fmt: skip


def skip_review(
    store: WorkStore,
    slug: str,
    *,
    trigger: Literal["build", "manual", "approval"],
    budget: int,
    brain: ReviewBrain | None = None,
    on_event: Callable[[ReviewEvent], None] = lambda e: None,
    now: Callable[[], str] = utc_now,
    uid: str | None = None,
) -> Review:
    """The review when there is no API key: only the steps that need no LLM job, `reproject`
    and `notice`. The review is recorded `skipped` (stop "no_api_key") with a `review_skipped`
    log line, and the last event has kind "skipped". The same ends as `review` otherwise:
    `stopped` (brain_unavailable) or `failed`. Returns the running review, with no event and
    nothing written, when a review is already running. `uid` as in `review`."""
    uid, started = uid or review_uid(), now()
    start = {"uid": uid, "trigger": trigger, "budget": budget, "now": started}
    if not store.write("ledger/review_start", DB_USER, start):
        [current] = store.read("ledger/review_current", {})
        return Review(**current)
    brain = brain or decide.DEFAULT_BRAIN
    state: Literal["skipped", "stopped", "failed"] = "skipped"
    stop: str | None = NO_API_KEY
    message = "Review skipped: no API key."
    try:
        on_event(ReviewEvent("start", message=f"Review started ({trigger}, no API key)."))
        counts = reproject(store, slug, brain=brain, now=now())
        said = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in counts.items())
        reprojected = f"Re-projected accepted claims: {said}."
        on_event(ReviewEvent("step", step="reproject", message=reprojected))
        cap = get_settings().keeper_notice_cap
        new = notice(store, slug, cap=cap, brain=brain, now=now())
        on_event(ReviewEvent("step", step="notice", message=f"Noticed {len(new)} new gap(s)."))
    except (BrainUnavailable, ResponseError) as e:
        state, stop = "stopped", BRAIN_UNAVAILABLE
        message = f"Review stopped: the brain is unavailable ({type(e).__name__}: {e})."
    except Exception as e:
        state, stop = "failed", f"{type(e).__name__}: {e}"[:300]
        message = f"Review failed: {stop}"
    finally:  # whatever happened above, the review does not stay `running`
        ended = now()
        store.write("ledger/review_finish", DB_USER,
                    {"uid": uid, "state": state, "stop": stop, "now": ended})  # fmt: skip
        log(store, ended, "keeper", f"review_{state}", why=f"{uid}: {stop}")
    on_event(ReviewEvent(state, message=message))
    return Review(uid=uid, slug=slug, trigger=trigger, state=state, budget=budget,
                  started_at=started, ended_at=ended, stop=stop)  # fmt: skip


@dataclass
class _Run:
    store: WorkStore
    slug: str
    brain: ReviewBrain
    client_for: Callable[[str, str], Any]
    graph_run: Runner | None
    on_event: Callable[[ReviewEvent], None]
    should_stop: Callable[[], bool]
    now: Callable[[], str]
    uid: str  # the Review's
    _n: int = 0  # the last step's number
    _n_lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self.picked: dict[str, int] = {}  # gap uid -> its attempts when picked, in pick order
        self.brain_error: Exception | None = None  # raised inside a job's write, re-raised after

    def steps(self, budget: int) -> None:
        self.release_orphans()
        if not self.brain.graph_exists(self.slug):
            raise BrainUnavailable(self.slug)
        counts = reproject(self.store, self.slug, brain=self.brain, now=self.now())
        said = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in counts.items())
        self.event("reproject", message=f"Re-projected accepted claims: {said}.")
        cap = get_settings().keeper_notice_cap
        new = notice(self.store, self.slug, cap=cap, brain=self.brain, now=self.now())
        self.event("notice", message=f"Noticed {len(new)} new gap(s).")
        if budget > 0:
            self.pick(budget)
            self.consult()
            self.decide()
        self.follow_up()

    # --- steps --------------------------------------------------------------------------------

    def pick(self, budget: int) -> None:
        rows = self.store.read("ledger/gaps", {"statuses": ["open"], "limit": GAP_LIMIT})
        texts: list[str] = []
        for gap in pick_order([Gap(**r) for r in rows])[:budget]:
            moved = _set_gap(self.store, self.now(), gap.uid, ["open"], "in_review", "picked")
            if moved:
                self.picked[gap.uid] = gap.attempts
                texts.append(gap.text)
                self.event("pick", gap=gap.uid, message=gap.text)
        if self.picked:
            picked = {"uid": self.uid, "gaps": list(self.picked), "gap_text": texts[0]}
            self.store.write("ledger/review_picked", DB_USER, picked)

    def consult(self) -> None:
        for gap, attempt in self.picked.items():
            for role in CONSULTED_BY:
                now = self.now()
                params = {"gap": gap, "role": role, "attempt": attempt, "now": now}
                [row] = self.store.write("ledger/post_consult", DB_USER, params)
                if row["created"]:
                    log(self.store, now, "keeper", "consulted", gap=gap, why=f"asked {role}")
            self.event("consult", gap=gap, message=f"Asked {' and '.join(CONSULTED_BY)}.")

        queues: dict[str, dict[str, Subject]] = {}
        for role in CONSULTED_BY:
            job = ROLES[role].job("consult")
            queues[role] = {
                s.data["gap"]: s
                for s in job.queue(self.store, self.ctx(role))
                if self.picked.get(s.data["gap"]) == s.data.get("attempt")  # this attempt only
            }
        for gap in self.picked:
            for role in CONSULTED_BY:
                subject = queues[role].get(gap)
                if subject is not None:
                    self.run(role, "consult", subject, gap=gap)

    def decide(self) -> None:
        job = ROLES["keeper"].job("decide")
        for subject in job.queue(self.store, self.ctx("keeper")):
            if subject.uid in self.picked:
                self.run("keeper", "decide", subject, gap=subject.uid)

    def follow_up(self) -> None:
        """pm's follow-up job once per claim in its queue. A run that opens no task is recorded
        (`ledger/follow_up_tried`, logged `follow_up_skipped`), which takes the claim out of the
        queue: otherwise every later review, even each budget-0 one after an approval, would
        pay for the same job again."""
        job = ROLES["pm"].job("follow_up")
        for subject in job.queue(self.store, self.ctx("pm")):  # read once: each claim at most once
            gap = subject.data.get("gap")
            result = self.run("pm", "follow_up", subject, gap=gap, claim=subject.uid)
            if result.rows:
                continue
            now = self.now()
            tried = {"claim": subject.uid, "now": now}
            if self.store.write("ledger/follow_up_tried", DB_USER, tried):
                why = f"no follow-up opened ({result.stop or 'no_write'}); not tried again"
                log(self.store, now, "pm", "follow_up_skipped", gap=gap, claim=subject.uid, why=why)

    def release_orphans(self) -> None:
        """Gaps an earlier review left in review with no claim waiting for a lead (a killed
        process, a failed finish) go back to `open`. Only one review runs at a time, so no
        other run owns them."""
        rows = self.store.read("ledger/gaps", {"statuses": ["in_review"], "limit": GAP_LIMIT})
        n = sum(self.release_gap(g["uid"], "left in review by an earlier review") for g in rows)
        if n:
            self.event("release", message=f"Released {n} gap(s) an earlier review left in review.")

    def release(self, reason: str) -> None:
        """Gaps this run picked that are still in review with no claim waiting for a lead go
        back to `open` (no attempt used): a consult or decision that never came, or an early
        end."""
        for gap in self.picked:
            self.release_gap(gap, reason)

    def release_gap(self, gap: str, reason: str) -> bool:
        """in_review -> open, no attempt used, logged `gap_released`; not when a claim of the
        gap waits for a lead (the gap stays in review until the lead acts)."""
        waiting = {"gap": gap, "statuses": ["pending_approval"]}
        if self.store.read("ledger/claims_for_gap", waiting):
            return False
        now = self.now()
        if not _set_gap(self.store, now, gap, ["in_review"], "open", reason):
            return False
        log(self.store, now, "keeper", "gap_released", gap=gap, why=reason)
        return True

    # --- one job ------------------------------------------------------------------------------

    def run(
        self, role: str, name: str, subject: Subject, *, gap: str | None, claim: str | None = None
    ) -> RunResult:
        """One job. Raises `_Stop` / `BrainUnavailable` instead of returning when the run must
        end (before the job, or when its write was refused for that reason)."""
        if self.should_stop():
            raise _Stop(REQUESTED)
        if not self.brain.graph_exists(self.slug):
            raise BrainUnavailable(self.slug)
        step = f"{role}.{name}"
        self.event(step, gap=gap, claim=claim, message=f"{role} {name} on {subject.uid}")
        result = run_job(
            self.store,
            ROLES[role],
            self.job(role, name),
            subject,
            self.ctx(role),
            client=self.client_for(role, name),
            graph_run=self.tracked(role),
        )
        self.submit_step(role, self.job(role, name).submit.name, subject, result)
        if self.brain_error is not None:
            raise self.brain_error
        written = next((r for r in result.rows if str(r.get("uid", "")).startswith("claim:")), {})
        wrote = ", ".join(str(r.get("status") or r.get("uid")) for r in result.rows)
        outcome = f"claim {written.get('status')}" if written else (result.stop or wrote)
        self.event(step, gap=gap, claim=written.get("uid") or claim, message=outcome)
        return result

    def job(self, role: str, name: str) -> Job:
        """The role's job, its writes refused when brain_<slug> is gone, passing the review's
        brain (keeper.decide), and letting a missing brain or a FalkorDB error through
        `run_job`, which catches job errors."""
        job = ROLES[role].job(name)
        base = job.apply
        brain = self.brain

        def apply(store: WorkStore, ctx: Ctx, s: Subject, sub: Any) -> list[dict[str, Any]]:
            if self.should_stop():  # asked while the job thought (a rebuild is emptying the
                self.brain_error = _Stop(REQUESTED)  # brain): what it read may be gone already
                raise self.brain_error
            try:
                # The loop turns graph-tool errors into tool results, so a brain that vanished
                # mid-run looks like "nothing found": write nothing from such a run.
                brain_present(brain, self.slug)
                if (role, name) == ("keeper", "decide"):
                    return base(store, ctx, s, sub, brain)  # type: ignore[call-arg]
                return base(store, ctx, s, sub)
            except (BrainUnavailable, ResponseError) as e:
                self.brain_error = e
                raise

        return replace(job, apply=apply)

    # --- steps on the activity trail ----------------------------------------------------------

    def tracked(self, role: str) -> Runner:
        """The graph-tool runner for one job of `role`: each call is a step, written `running`
        before it runs and finished with what it returned (or its error, which is re-raised so
        the loop still reports it to the model)."""
        if self.graph_run is not None:
            base = self.graph_run
        else:
            from brain import tools as graph_tools

            base = graph_tools.call

        def run(slug: str, name: str, **params: Any) -> list[Any]:
            n = self.step(role, name, "graph", params, "running")
            try:
                rows = base(slug, name, **params)
            except Exception as e:
                self.finish(n, "failed", error=f"{type(e).__name__}: {e}"[:300])
                raise
            try:  # drawing the step must never change what the job sees
                data = [r.model_dump(mode="json", by_alias=True) if hasattr(r, "model_dump")
                        else r for r in rows]  # fmt: skip
                nodes, _ = subgraph(name, params, data)
                touched = list(dict.fromkeys(nd["uid"] for nd in nodes if nd.get("uid")))
            except Exception:
                _log.warning("could not draw step %s of %s", n, self.uid, exc_info=True)
                touched = []
            self.finish(n, "done", count=len(rows), touched=touched)
            return rows

        return run

    def submit_step(self, role: str, tool: str, subject: Subject, result: RunResult) -> None:
        """The job's submit as one step: `done` when it wrote, else `failed` with why."""
        summary: dict[str, Any] = {"subject": subject.uid}
        summary.update({k: result.submit[k] for k in SUBMIT_KEYS if k in (result.submit or {})})
        claim = next((r["uid"] for r in result.rows if str(r.get("uid", "")).startswith("claim:")),
                     None)  # fmt: skip
        if claim:
            summary["claim"] = claim
        status = "done" if result.rows else "failed"
        self.step(role, tool, "submit", summary, status,
                  error=None if result.rows else (result.stop or "no_write"))  # fmt: skip

    def step(self, actor: str, tool: str, kind: str, params: dict[str, Any], status: str,
             **ended: Any) -> int:  # fmt: skip
        with self._n_lock:
            self._n += 1
            n = self._n
        row = {"review": self.uid, "n": n, "actor": actor, "tool": tool, "kind": kind,
               "input": json.dumps(params, default=str, ensure_ascii=False), "status": status,
               "at": self.now(), **ended}  # fmt: skip
        self._write_step("ledger/write_step", row)
        return n

    def finish(self, n: int, status: str, **ended: Any) -> None:
        row = {"review": self.uid, "n": n, "status": status, "at": self.now(), **ended}
        self._write_step("ledger/finish_step", row)

    def _write_step(self, name: str, row: dict[str, Any]) -> None:
        try:
            self.store.write(name, DB_USER, row)
        except Exception:  # best effort: the trail must never change a job's outcome
            _log.warning("could not write a step of %s", self.uid, exc_info=True)

    def ctx(self, role: str) -> Ctx:
        """Ledger timestamps are ISO text; `iso()` passes them through (as decide._ctx does)."""
        return Ctx(f"agent:{role}", ROLES[role].db_user, self.now())  # type: ignore[arg-type]

    def event(self, step: str, **fields: Any) -> None:
        self.on_event(ReviewEvent("step", step=step, **fields))
