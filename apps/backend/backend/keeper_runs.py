"""Keeper review runs for the API: one review per company at a time, in a worker thread, with
its progress for the Keeper page.

Why: a review (`agents.keeper.review`) runs LLM jobs for minutes, so a request only starts,
follows or stops it. The app runs one after each finished build (budget `keeper_build_budget`),
on "Review now" (`keeper_budget`) and after an approval (budget 0, so pm's follow-up shows).

- `start` returns the company's running review when there is one (this process's, or, through
  the ledger's own guard, another process's), else starts one and returns it once the ledger
  has recorded it.
- Without an API key (`has_key`) every run is `skip_review`: re-projection and noticing only,
  recorded `skipped`. No LLM job runs, also not a budget-0 follow-up.
- A stop sets a flag the review checks between jobs.
- `subscribe` replays the events of the company's latest run in this process, then follows it
  live, then ends; so a page that opens the stream after a quick run still sees all of it.
- `recover` (at startup) marks a review a previous server process left `running` as stopped
  (`ledger/review_stop_running`). It only reads a company whose ledger has no running review,
  so it never creates keeper_<slug>.

Every seam (`store_for`, `client_for`, `has_key`, `brain`, `graph_run`) defaults to a module
function, taken when the KeeperRuns is made (not at call time, as `api.ask.Asker` does): a run
lives in its own thread and may outlast the test that patched those functions, and must never
fall back to a real keeper_<slug> or Claude then. The API tests patch them before they make
the app, so every run they start stays offline.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from agents import llm
from agents.keeper import decide
from agents.keeper.decide import DB_USER, BrainFacts
from agents.keeper.gaps import utc_now
from agents.keeper.model import Review
from agents.keeper.review import ReviewEvent, review, skip_review
from agents.keeper.store import KeeperStore
from agents.toolset import Runner
from agents.work.store import WorkStore
from brain.config import get_settings

from backend import registry

log = logging.getLogger(__name__)

Trigger = Literal["build", "manual", "approval"]
ENDS: tuple[str, ...] = ("done", "stopped", "failed", "skipped")  # the kinds that end a run
START_WAIT_SECONDS = 10.0  # how long `start` waits for the ledger to record the review


# --- the defaults (module functions, so tests can swap them) ----------------------------------


def keeper_store(slug: str) -> WorkStore:
    return KeeperStore(slug)


def has_api_key() -> bool:
    """A key in .env (Settings) or in the environment, as `agents keeper review` checks."""
    return bool(get_settings().anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY"))


def claude_for(role: str, job: str) -> Any:
    return llm.client()


def default_brain() -> BrainFacts:
    return decide.DEFAULT_BRAIN


def default_graph_run() -> Runner | None:
    """None: the jobs' graph tools run the real `brain.tools`."""
    return None


class ReviewNotStarted(Exception):
    """The ledger did not record the review in time (FalkorDB slow or refusing)."""


@dataclass(eq=False)
class _Run:
    slug: str
    stop: threading.Event = field(default_factory=threading.Event)
    started: threading.Event = field(default_factory=threading.Event)  # first event, or the end
    done: threading.Event = field(default_factory=threading.Event)  # set with `ended`
    events: list[ReviewEvent] = field(default_factory=list)
    ended: bool = False
    result: Review | None = None


@dataclass(eq=False)
class _Subscriber:
    slug: str
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[ReviewEvent | None]  # None: the run is over


class KeeperRuns:
    def __init__(
        self,
        store_for: Callable[[str], WorkStore] | None = None,
        client_for: Callable[[str, str], Any] | None = None,
        has_key: Callable[[], bool] | None = None,
        brain: BrainFacts | None = None,
        graph_run: Runner | None = None,
        start_wait: float = START_WAIT_SECONDS,
    ):
        self.store_for = store_for or keeper_store
        self.client_for = client_for or claude_for
        self.has_key = has_key or has_api_key
        self._brain = brain
        self._graph_run = graph_run
        self._default_brain = default_brain
        self._default_graph_run = default_graph_run
        self.start_wait = start_wait
        self._lock = threading.RLock()  # the run table, each run's events and the subscribers
        self._runs: dict[str, _Run] = {}  # the latest run per slug started by this process
        self._subscribers: set[_Subscriber] = set()

    @property
    def brain(self) -> BrainFacts:
        return self._brain if self._brain is not None else self._default_brain()

    @property
    def graph_run(self) -> Runner | None:
        return self._graph_run if self._graph_run is not None else self._default_graph_run()

    # --- public API ----------------------------------------------------------------------------

    def start(self, slug: str, trigger: Trigger, budget: int) -> Review:
        """The slug's running review, else a new one (see the module doc), once the ledger has
        recorded it. Raises ReviewNotStarted when, after `start_wait` seconds, the run has not
        ended and the ledger's latest review is not a running one (an older review is never
        returned as the new one)."""
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
        wait). Raises only when the worker thread cannot start; the run logs its own errors."""
        self._launch(slug, trigger, budget)

    def _launch(self, slug: str, trigger: Trigger, budget: int) -> _Run:
        """The slug's live run in this process, else a new one in a worker thread."""
        with self._lock:
            run = self._runs.get(slug)
            if run is not None and not run.ended:
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
            run = self._runs.get(slug)
            if run is None or run.ended:
                return False
            run.stop.set()
            return True

    def running(self, slug: str) -> bool:
        with self._lock:
            run = self._runs.get(slug)
            return run is not None and not run.ended

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

    def subscribe(self, slug: str) -> Subscription:
        """The events of the slug's latest run in this process: the ones so far, then the live
        ones, then the end. Call it from the event loop that will iterate it; `aclose` it."""
        sub = _Subscriber(slug, asyncio.get_running_loop(), asyncio.Queue())
        with self._lock:
            run = self._runs.get(slug)
            for event in run.events if run is not None else []:
                sub.queue.put_nowait(event)
            if run is None or run.ended:
                sub.queue.put_nowait(None)
            else:
                self._subscribers.add(sub)
        return Subscription(self, sub)

    def recover(self) -> None:
        """On startup: a review still `running` in a company's ledger belonged to a process that
        is gone. Best effort per company; a company with no ledger is skipped."""
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
            if self.has_key():
                run.result = review(
                    store,
                    run.slug,
                    budget=budget,
                    trigger=trigger,
                    client_for=self.client_for,
                    graph_run=self.graph_run,
                    brain=self.brain,  # type: ignore[arg-type]  # DEFAULT_BRAIN also notices
                    on_event=on_event,
                    should_stop=run.stop.is_set,
                )
            else:
                run.result = skip_review(
                    store,
                    run.slug,
                    trigger=trigger,
                    budget=budget,
                    brain=self.brain,  # type: ignore[arg-type]
                    on_event=on_event,
                )
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
                        self._deliver(sub, None)
                        self._subscribers.discard(sub)
                run.done.set()
            run.started.set()

    def _emit(self, run: _Run, event: ReviewEvent) -> None:
        with self._lock:
            run.events.append(event)
            for sub in list(self._subscribers):
                if sub.slug == run.slug:
                    self._deliver(sub, event)

    def _deliver(self, sub: _Subscriber, item: ReviewEvent | None) -> None:
        try:
            sub.loop.call_soon_threadsafe(sub.queue.put_nowait, item)
        except RuntimeError:  # its event loop is closed: nobody is listening any more
            self._subscribers.discard(sub)

    def _unsubscribe(self, sub: _Subscriber) -> None:
        with self._lock:
            self._subscribers.discard(sub)


class Subscription:
    """What `subscribe` returns: an async iterator of one run's events that stops at its end.
    Not an async generator, so `aclose()` unregisters even when it was never iterated (as
    `jobs.Subscription`)."""

    def __init__(self, runs: KeeperRuns, sub: _Subscriber):
        self._runs = runs
        self._sub = sub

    def __aiter__(self) -> Subscription:
        return self

    async def __anext__(self) -> ReviewEvent:
        item = await self._sub.queue.get()
        if item is None:
            raise StopAsyncIteration
        return item

    async def aclose(self) -> None:
        self._runs._unsubscribe(self._sub)
