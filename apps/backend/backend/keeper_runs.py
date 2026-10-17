"""Keeper review runs for the API: one review per company at a time, in a worker thread, with
its progress for the Keeper page.

Why: a review (`agents.keeper.review`) runs LLM jobs for minutes, so a request only starts,
follows or stops it. The app runs one after each finished build (budget `keeper_build_budget`),
on "Review now" (`keeper_budget`) and after an approval (budget 0, so pm's follow-up shows).

- `start` returns the company's running review when there is one (this process's, or, through
  the ledger's own guard, another process's), else starts one and returns it once the ledger
  has recorded it. A "build" start that finds this process's review running is kept pending
  and starts (with its budget) when that review ends, so a finished build is always reviewed.
- While the company builds (`building`, the app's `JobRunner.building`) nothing starts:
  `start` and `start_soon` raise `BrainBuilding`, and the brain the reviews see reads as
  missing (`graph_exists` False), so a running review stops `brain_unavailable` instead of
  judging claims against the rebuild's empty brain_<slug>. A rebuild calls `stop_for_rebuild`
  before it drops the graph: mark the run `rebuilt`, stop, then wait up to `rebuild_wait`
  seconds for the end. A rebuilt run's brain reads as missing for the rest of the run, also
  once the build is over, so a job whose tool loop spanned the rebuild (its reads empty or
  partial) writes nothing; the review ends stopped `brain_unavailable`, its gaps open again.
- Without an API key (`has_key`) every run is `skip_review`: re-projection and noticing only,
  recorded `skipped`. No LLM job runs, also not a budget-0 follow-up.
- A stop sets a flag the review checks between jobs; the job running then still writes.
- `is_running(slug, uid)` says whether this process is running that review (the run's uid is
  made here and handed to the review), so the activity route can tell a live review from one a
  server lost.
- `subscribe` replays the events of the company's latest run in this process, then follows it
  live, then ends; so a page that opens the stream after a quick run still sees all of it.
- `recover` (at startup) marks a review a previous server process left `running` as stopped
  (`ledger/review_stop_running`), only once its heartbeat is `REVIEW_STALE_SECONDS` old: a
  review another process runs (`agents keeper review`) keeps beating, so neither a (re)start
  nor a new start (`ledger/review_start` stops only a stale one) overlaps it. It only writes
  for a company whose latest review is running, so it never creates keeper_<slug>.

Every seam (`store_for`, `client_for`, `has_key`, `brain`, `graph_run`) defaults to a module
function, taken when the KeeperRuns is made (not at call time, as `api.ask.Asker` does): a run
lives in its own thread and may outlast the test that patched those functions, and must never
fall back to a real keeper_<slug> or Claude then. The API tests patch them before they make
the app, so every run they start stays offline.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from agents import llm
from agents.keeper import decide
from agents.keeper.decide import DB_USER, BrainFacts
from agents.keeper.gaps import utc_now
from agents.keeper.model import Review, review_uid
from agents.keeper.review import ReviewEvent, review, skip_review
from agents.keeper.store import KeeperStore
from agents.toolset import Runner
from agents.work.store import WorkStore

from backend import registry
from backend.fanout import Subscriber, Subscription, deliver

log = logging.getLogger(__name__)

Trigger = Literal["build", "manual", "approval"]
ENDS: tuple[str, ...] = ("done", "stopped", "failed", "skipped")  # the kinds that end a run
START_WAIT_SECONDS = 10.0  # how long `start` waits for the ledger to record the review
REBUILD_WAIT_SECONDS = 10.0  # how long a rebuild waits for the review it stopped to end
BUILDING = decide.BUILDING  # the sentence a refusal while the company builds says


# --- the defaults (module functions, so tests can swap them) ----------------------------------


def keeper_store(slug: str) -> WorkStore:
    return KeeperStore(slug)


def has_api_key() -> bool:
    """A key in .env (Settings) or in the environment, as `agents keeper review` checks."""
    return llm.has_api_key()


def claude_for(role: str, job: str) -> Any:
    return llm.client()


def default_brain() -> BrainFacts:
    return decide.DEFAULT_BRAIN


def default_graph_run() -> Runner | None:
    """None: the jobs' graph tools run the real `brain.tools`."""
    return None


class ReviewNotStarted(Exception):
    """The ledger did not record the review in time (FalkorDB slow or refusing)."""


class BrainBuilding(Exception):
    """The company is building: no review starts (its brain may be empty for now)."""

    def __init__(self, slug: str):
        super().__init__(BUILDING)
        self.slug = slug


class _BuildingAware:
    """The review's brain facts, with brain_<slug> missing while the company builds, and, for a
    run's brain, from the moment a rebuild touched the run (`rebuilt`): the review and decide
    steps already stop (`BrainUnavailable`) on a missing brain before any write an empty one
    would make wrong. Asked after the real check, so a check that was waiting when a rebuild
    began still says "missing"."""

    def __init__(
        self,
        brain: BrainFacts,
        building: Callable[[str], bool],
        rebuilt: Callable[[], bool] = lambda: False,
    ):
        self._brain = brain
        self._building = building
        self._rebuilt = rebuilt

    def graph_exists(self, slug: str) -> bool:
        exists = self._brain.graph_exists(slug)
        return exists and not self._building(slug) and not self._rebuilt()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._brain, name)


@dataclass(eq=False)
class _Run:
    slug: str
    uid: str = field(default_factory=review_uid)  # the review it runs (unless one was running)
    stop: threading.Event = field(default_factory=threading.Event)
    rebuilt: threading.Event = field(default_factory=threading.Event)  # never cleared
    started: threading.Event = field(default_factory=threading.Event)  # first event, or the end
    done: threading.Event = field(default_factory=threading.Event)  # set with `ended`
    events: list[ReviewEvent] = field(default_factory=list)
    ended: bool = False
    result: Review | None = None


class KeeperRuns:
    def __init__(
        self,
        store_for: Callable[[str], WorkStore] | None = None,
        client_for: Callable[[str, str], Any] | None = None,
        has_key: Callable[[], bool] | None = None,
        brain: BrainFacts | None = None,
        graph_run: Runner | None = None,
        start_wait: float = START_WAIT_SECONDS,
        building: Callable[[str], bool] | None = None,
        rebuild_wait: float = REBUILD_WAIT_SECONDS,
    ):
        self.store_for = store_for or keeper_store
        # Whether the slug is building (the app sets the job runner's); read on every call.
        self.building: Callable[[str], bool] = building or (lambda slug: False)
        self.rebuild_wait = rebuild_wait
        self.client_for = client_for or claude_for
        self.has_key = has_key or has_api_key
        self._brain = brain
        self._graph_run = graph_run
        self._default_brain = default_brain
        self._default_graph_run = default_graph_run
        self.start_wait = start_wait
        self._lock = threading.RLock()  # the run table, each run's events and the subscribers
        self._runs: dict[str, _Run] = {}  # the latest run per slug started by this process
        self._pending: dict[str, int] = {}  # slug -> budget of a build review to run next
        self._subscribers: set[Subscriber[ReviewEvent]] = set()  # None on a queue: the run is over

    @property
    def brain(self) -> BrainFacts:
        """The brain facts approvals use: missing while the slug builds."""
        return self._brain_for(None)

    def _brain_for(self, run: _Run | None) -> BrainFacts:
        """The brain facts of one run (or of an approval, `None`): missing while the slug
        builds, and for the rest of the run once a rebuild touched it."""
        base = self._brain if self._brain is not None else self._default_brain()
        rebuilt = run.rebuilt.is_set if run is not None else (lambda: False)
        return _BuildingAware(base, lambda slug: self.building(slug), rebuilt)  # type: ignore[return-value]

    @property
    def graph_run(self) -> Runner | None:
        return self._graph_run if self._graph_run is not None else self._default_graph_run()

    # --- public API ----------------------------------------------------------------------------

    def start(self, slug: str, trigger: Trigger, budget: int) -> Review:
        """The slug's running review, else a new one (see the module doc), once the ledger has
        recorded it. Raises BrainBuilding while the slug builds, and ReviewNotStarted when,
        after `start_wait` seconds, the run has not ended and the ledger's latest review is not
        a running one (an older review is never returned as the new one)."""
        run = self._launch(slug, trigger, budget)
        run.started.wait(self.start_wait)
        if run.ended and run.result is not None:
            return run.result  # as it ended; or another process's running review
        current = self.current(slug)
        if current is None or not (run.ended or current.state == "running"):
            raise ReviewNotStarted(f"The review of {slug} did not start in time.")
        return current

    def start_soon(self, slug: str, trigger: Trigger, budget: int) -> None:
        """`start` without waiting for the ledger (after an approval, whose response must not
        wait). Raises BrainBuilding while the slug builds, or when the worker thread cannot
        start; the run logs its own errors."""
        self._launch(slug, trigger, budget)

    def _launch(self, slug: str, trigger: Trigger, budget: int) -> _Run:
        """The slug's live run in this process (a "build" start is kept pending until it ends),
        else a new one in a worker thread. The building check is under the lock, so a rebuild
        that begins after it finds this run when it stops the slug's review."""
        with self._lock:
            if self.building(slug):
                raise BrainBuilding(slug)
            run = self._live(slug)
            if run is not None:
                if trigger == "build":
                    self._pending[slug] = budget
                return run
            run = _Run(slug)
            self._runs[slug] = run
            worker = threading.Thread(
                target=self._work, args=(run, trigger, budget), name=f"keeper-{slug}", daemon=True
            )
            try:
                worker.start()
            except BaseException:
                run.ended = True
                run.done.set()
                run.started.set()
                raise
            return run

    def stop(self, slug: str) -> bool:
        """Ask the slug's running review to stop at its next job. False when none runs here."""
        with self._lock:
            run = self._live(slug)
            if run is None:
                return False
            run.stop.set()
            return True

    def stop_for_rebuild(self, slug: str) -> None:
        """A rebuild is about to drop brain_<slug>: mark the slug's review `rebuilt`, stop it
        and wait up to `rebuild_wait` seconds for it to end. A job still thinking then has its
        writes refused (the run's brain reads as missing from now on, also after the build), so
        the reset may go ahead."""
        with self._lock:
            self._pending.pop(slug, None)  # the rebuild's own hook reviews after it
            run = self._live(slug)
            if run is not None:
                run.rebuilt.set()
        if self.stop(slug) and not self.wait(slug, self.rebuild_wait):
            log.warning("the Keeper review of %s did not stop before its rebuild", slug)

    def running(self, slug: str) -> bool:
        with self._lock:
            return self._live(slug) is not None

    def is_running(self, slug: str, uid: str) -> bool:
        """This process is running the slug's review `uid` now."""
        with self._lock:
            run = self._live(slug)
            return run is not None and run.uid == uid

    def current(self, slug: str) -> Review | None:
        """The ledger's latest review of the slug (running or not), else None."""
        rows = self.store_for(slug).read("ledger/review_current", {})
        return Review(**rows[0]) if rows else None

    def wait(self, slug: str, timeout: float) -> bool:
        """Wait until the slug's run in this process ends; False on timeout."""
        with self._lock:
            run = self._runs.get(slug)
        if run is None:
            return True
        return run.done.wait(timeout)

    def subscribe(self, slug: str) -> Subscription[ReviewEvent]:
        """The events of the slug's latest run in this process: the ones so far, then the live
        ones, then the end. Call it from the event loop that will iterate it; `aclose` it."""
        sub: Subscriber[ReviewEvent] = Subscriber(slug, asyncio.get_running_loop(), asyncio.Queue())
        with self._lock:
            run = self._runs.get(slug)
            for event in run.events if run is not None else []:
                sub.queue.put_nowait(event)
            if run is None or run.ended:
                sub.queue.put_nowait(None)
            else:
                self._subscribers.add(sub)
        return Subscription(lambda: self._unsubscribe(sub), sub.queue)

    def recover(self) -> None:
        """On startup: a review still `running` in a company's ledger whose heartbeat is stale
        belonged to a process that is gone (a fresh one is another process's live review).
        Best effort per company; a company with no ledger is skipped."""
        for company in registry.list_companies():
            slug = company.slug
            if self.running(slug):
                continue
            try:
                current = self.current(slug)
                if current is not None and current.state == "running":
                    self.store_for(slug).write(
                        "ledger/review_stop_running", DB_USER, {"now": utc_now()}
                    )
            except Exception:
                log.warning("could not recover the Keeper reviews of %s", slug, exc_info=True)

    # --- worker --------------------------------------------------------------------------------

    def _work(self, run: _Run, trigger: Trigger, budget: int) -> None:
        def on_event(event: ReviewEvent) -> None:
            self._emit(run, event)
            run.started.set()

        try:
            store = self.store_for(run.slug)
            common: dict[str, Any] = {
                "budget": budget,
                "trigger": trigger,
                "brain": self._brain_for(run),  # DEFAULT_BRAIN also notices
                "on_event": on_event,
                "uid": run.uid,
            }
            if self.has_key():
                run.result = review(
                    store,
                    run.slug,
                    client_for=self.client_for,
                    graph_run=self.graph_run,
                    should_stop=run.stop.is_set,
                    **common,
                )
            else:
                run.result = skip_review(store, run.slug, **common)
        except Exception as exc:
            log.exception("Keeper review of %s failed", run.slug)
            if not any(e.kind in ENDS for e in run.events):  # subscribers must hear an end
                message = f"Review failed: {type(exc).__name__}: {exc}"[:300]
                self._emit(run, ReviewEvent("failed", message=message))
        finally:
            with self._lock:
                run.ended = True
                for sub in list(self._subscribers):
                    if sub.slug == run.slug:
                        deliver(sub, None)
                        self._subscribers.discard(sub)
                run.done.set()
            run.started.set()
        self._start_pending(run.slug)

    def _start_pending(self, slug: str) -> None:
        """The build review a finished build asked for while this one ran. Dropped while the
        slug builds again: that build's own hook reviews after it."""
        with self._lock:
            budget = self._pending.pop(slug, None)
        if budget is None:
            return
        try:
            self._launch(slug, "build", budget)
        except BrainBuilding:
            pass
        except Exception:
            log.exception("could not start the pending build review of %s", slug)

    def _emit(self, run: _Run, event: ReviewEvent) -> None:
        with self._lock:
            run.events.append(event)
            for sub in list(self._subscribers):
                if sub.slug == run.slug and not deliver(sub, event):
                    self._subscribers.discard(sub)

    def _live(self, slug: str) -> _Run | None:
        """The slug's run in this process while it has not ended. Call it holding the lock."""
        run = self._runs.get(slug)
        return run if run is not None and not run.ended else None

    def _unsubscribe(self, sub: Subscriber[ReviewEvent]) -> None:
        with self._lock:
            self._subscribers.discard(sub)
