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
    6. follow up  pm's follow_up job, once per claim in its queue (not budgeted)
    7. finish     `ledger/review_finish("done")`

`budget=0` runs only 1, 2, 6 and 7 (the backend's run after an approval, so the follow-up shows).
Every job goes through `runner.run_job` with `client_for(role, job)`: `llm.client()` in
production, `policies.offline_client` offline.

The run ends early, between jobs:
- `should_stop()` -> `stopped`, stop "requested".
- brain_<slug> missing (`graph_exists` False, `BrainUnavailable`) or a FalkorDB `ResponseError`
  -> `stopped`, stop "brain_unavailable". `run_job` catches a job's errors, so the jobs' writes
  are wrapped to pass these two through.
- anything else -> `failed`, its message in `stop`.

Whatever the end, the gaps this run moved to in_review and left undecided (still in_review, no
claim waiting for a lead) go back to `open` without using an attempt, so the next review can
pick them; a run first does the same for gaps an earlier run left behind (a killed process).
Each is logged `gap_released`. Every job's writes are refused when brain_<slug> is gone: the loop
turns graph-tool errors into tool results, so such a run would record "nothing found". Every step
emits a `ReviewEvent`; every end, even an unexpected one, finishes the review and writes the
LogEntry `review_<state>`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol

from brain.config import get_settings
from redis.exceptions import ResponseError

from agents.keeper import decide
from agents.keeper.decide import (
    DB_USER,
    BrainFacts,
    BrainUnavailable,
    _log,
    _set_gap,
    brain_present,
)
from agents.keeper.gaps import utc_now
from agents.keeper.model import Gap, Review, review_uid
from agents.keeper.notice import notice
from agents.keeper.project import reproject
from agents.keeper.rules import pick_order
from agents.roles import ROLES
from agents.roles.base import Ctx, Job, Subject
from agents.runner import run_job
from agents.toolset import Runner
from agents.work.store import WorkStore

GAP_LIMIT = 10_000  # open gaps read for picking (pick_order needs all of them)
CONSULTED_BY = ("pm", "qa")
REQUESTED = "requested"  # stop: should_stop() said so
BRAIN_UNAVAILABLE = "brain_unavailable"  # stop: brain_<slug> is gone or FalkorDB refused

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
) -> Review:
    """Run one review (see the module doc). Returns the review as it ended, or the running one
    when a review is already running. `brain` defaults to `decide.DEFAULT_BRAIN`, read now."""
    uid, started = review_uid(), now()
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
                       on_event, should_stop, now)  # fmt: skip
            _log(store, started, "keeper", "review_start", why=f"{uid}: {trigger}, budget {budget}")
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
        _log(store, ended, "keeper", f"review_{state}", why=f"{uid}: {stop or state}")
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

    def __post_init__(self) -> None:
        self.picked: dict[str, int] = {}  # gap uid -> its attempts when picked, in pick order
        self.brain_error: Exception | None = None  # raised inside a job's write

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
        for gap in pick_order([Gap(**r) for r in rows])[:budget]:
            moved = _set_gap(self.store, self.now(), gap.uid, ["open"], "in_review", "picked")
            if moved:
                self.picked[gap.uid] = gap.attempts
                self.event("pick", gap=gap.uid, message=gap.text)

    def consult(self) -> None:
        for gap, attempt in self.picked.items():
            for role in CONSULTED_BY:
                now = self.now()
                params = {"gap": gap, "role": role, "attempt": attempt, "now": now}
                [row] = self.store.write("ledger/post_consult", DB_USER, params)
                if row["created"]:
                    _log(self.store, now, "keeper", "consulted", gap=gap, why=f"asked {role}")
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
        job = ROLES["pm"].job("follow_up")
        for subject in job.queue(self.store, self.ctx("pm")):  # read once: each claim at most once
            self.run("pm", "follow_up", subject, gap=subject.data.get("gap"), claim=subject.uid)

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
        _log(self.store, now, "keeper", "gap_released", gap=gap, why=reason)
        return True

    # --- one job ------------------------------------------------------------------------------

    def run(
        self, role: str, name: str, subject: Subject, *, gap: str | None, claim: str | None = None
    ) -> None:
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
            graph_run=self.graph_run,
        )
        if self.brain_error is not None:
            raise self.brain_error
        written = next((r for r in result.rows if str(r.get("uid", "")).startswith("claim:")), {})
        wrote = ", ".join(str(r.get("status") or r.get("uid")) for r in result.rows)
        outcome = f"claim {written.get('status')}" if written else (result.stop or wrote)
        self.event(step, gap=gap, claim=written.get("uid") or claim, message=outcome)

    def job(self, role: str, name: str) -> Job:
        """The role's job, its writes refused when brain_<slug> is gone, passing the review's
        brain (keeper.decide), and letting a missing brain or a FalkorDB error through
        `run_job`, which catches job errors."""
        job = ROLES[role].job(name)
        base = job.apply
        brain = self.brain

        def apply(store: WorkStore, ctx: Ctx, s: Subject, sub: Any) -> list[dict[str, Any]]:
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

    def ctx(self, role: str) -> Ctx:
        """Ledger timestamps are ISO text; `iso()` passes them through (as decide._ctx does)."""
        return Ctx(f"agent:{role}", ROLES[role].db_user, self.now())  # type: ignore[arg-type]

    def event(self, step: str, **fields: Any) -> None:
        self.on_event(ReviewEvent("step", step=step, **fields))
