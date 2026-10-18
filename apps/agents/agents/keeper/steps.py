"""A run's steps on the ledger, for the Systems page's activity trail (`agents/activity.py`).

Why: a Keeper review and an Archivist run both show their agents' work step by step. Each tool
call is a `ReviewStep` (`ledger/write_step`), written `running` when it starts and finished
(`ledger/finish_step`) `done` or `failed`, with its row count and the brain uids it touched
(`agents.walk.subgraph`); a job's submit is one more step, `failed` when it wrote nothing.
Steps hang off a parent: a Review's uid, or an ArchiveRequest's. They are numbered 1.. under it,
in the order they ran (a lock keeps the count right across threads).

    trail = StepTrail(store, review_uid, "citadel_keeper", now)
    run = trail.wrap(graph_tools.call, "pm")         # each call becomes a step
    trail.submit_step("pm", "submit_consult", {"subject": ...}, result)

Writes are best effort: a ledger hiccup never changes what a job sees or does.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from agents.keeper.gaps import utc_now
from agents.toolset import Runner
from agents.walk import subgraph
from agents.work.store import WorkStore

if TYPE_CHECKING:
    from agents.runner import RunResult

_log = logging.getLogger(__name__)

Draw = Callable[[str, dict[str, Any], list[Any]], tuple[list[dict], list[dict]]]


class StepTrail:
    def __init__(
        self,
        store: WorkStore,
        parent: str,
        db_user: str,
        now: Callable[[], str] = utc_now,
        draw: Draw = subgraph,
    ) -> None:
        self.store = store
        self.parent = parent  # the Review's or ArchiveRequest's uid
        self.db_user = db_user
        self.now = now
        self.draw = draw  # (tool, params, rows) -> (nodes, rels): what a call touched
        self._n = 0  # the last step's number
        self._lock = threading.Lock()

    def wrap(self, run: Runner, actor: str) -> Runner:
        """`run` with each call a step of `actor`: written `running` before it runs, finished
        with what it returned, or with its error (re-raised, so the loop still reports it)."""

        def tracked(slug: str, name: str, **params: Any) -> list[Any]:
            n = self.step(actor, name, "graph", params, "running")
            try:
                rows = run(slug, name, **params)
            except Exception as e:
                self.finish(n, "failed", error=f"{type(e).__name__}: {e}"[:300])
                raise
            self.finish(n, "done", count=len(rows), touched=self._touched(n, name, params, rows))
            return rows

        return tracked

    def submit_step(
        self, actor: str, tool: str, summary: dict[str, Any], result: RunResult
    ) -> None:
        """The job's submit as one step: `done` when it wrote, else `failed` with why."""
        status = "done" if result.rows else "failed"
        self.step(actor, tool, "submit", summary, status,
                  error=None if result.rows else (result.stop or "no_write"))  # fmt: skip

    def step(
        self, actor: str, tool: str, kind: str, params: dict[str, Any], status: str, **ended: Any
    ) -> int:
        with self._lock:
            self._n += 1
            n = self._n
        row = {"review": self.parent, "n": n, "actor": actor, "tool": tool, "kind": kind,
               "input": json.dumps(params, default=str, ensure_ascii=False), "status": status,
               "at": self.now(), **ended}  # fmt: skip
        self._write("ledger/write_step", row)
        return n

    def finish(self, n: int, status: str, **ended: Any) -> None:
        row = {"review": self.parent, "n": n, "status": status, "at": self.now(), **ended}
        self._write("ledger/finish_step", row)

    def _touched(self, n: int, name: str, params: dict[str, Any], rows: list[Any]) -> list[str]:
        """The brain uids a call touched; drawing it must never change what the job sees."""
        try:
            data = [r.model_dump(mode="json", by_alias=True) if hasattr(r, "model_dump")
                    else r for r in rows]  # fmt: skip
            nodes, _ = self.draw(name, params, data)
            return list(dict.fromkeys(nd["uid"] for nd in nodes if nd.get("uid")))
        except Exception:
            _log.warning("could not draw step %s of %s", n, self.parent, exc_info=True)
            return []

    def _write(self, name: str, row: dict[str, Any]) -> None:
        try:
            self.store.write(name, self.db_user, row)
        except Exception:  # best effort: the trail must never change a job's outcome
            _log.warning("could not write a step of %s", self.parent, exc_info=True)
