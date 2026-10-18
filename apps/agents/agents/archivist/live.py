"""Ask's `ask_archivist` tool: the Archivist's job run inline, in the Ask worker thread.

    recall (rule 15: answered lately -> that answer and its finds, reason "remembered", no run)
    -> open the request (asked_by ask; the same question in flight is returned instead)
       created        -> answer_request(tier ask), its steps forwarded to Ask's stream
       Ask's, in flight -> join: read it every `poll` s until it ends or the Ask timeout passes
       Keeper's, open   -> "queued": the next review runs it, Ask does not wait for it
    -> one row: {request, outcome, summary, partial, reason, calls, finds}

Why inline: Ask cites what was loaded in the same answer, so the finds' uids join `seen`.
Deadlines (rule 8), from the run's start: past 0.7 x `archivist_ask_timeout` the source tools ask
the model to submit (`wrap_up`); past the timeout, or when the Ask stream closes (`ASK_STOP`),
the run ends at its next step with nothing applied (`should_stop`).

Isolation: the inner run is another LangGraph graph run from inside Ask's `run_tools` node.
LangGraph finds its parent run through a contextvar, so the inner run would save checkpoints
into Ask's thread (as a subgraph) and could stream into Ask's stream. It runs in an empty
`contextvars.Context` and is compiled with `checkpointer=False` (`runner._run_loop`); its
chunks reach Ask only through `writer` (called back in a copy of Ask's context), wrapped as
`{"kind": "archive_step", "parent": <the Ask call id>, "event": <llm | step | step_done>, ...}`.

Never raises: a failure, refusal or timeout is a normal row with `reason`, so Ask answers with
what it has and says what it could not reach.
"""

from __future__ import annotations

import contextvars
import logging
import re
import threading
import time
from collections.abc import Callable
from typing import Any, Literal

import anthropic
from brain.config import get_settings
from pydantic import BaseModel, ConfigDict, Field

from agents.archivist import rules
from agents.archivist.job import answer_request
from agents.keeper.gaps import utc_now
from agents.keeper.model import ArchiveRequest, archive_uid
from agents.work.store import WorkStore

_log = logging.getLogger(__name__)

NAME = "ask_archivist"
WRITER = "citadel_brain"  # Ask opens requests as its own user (acl.py)
POLL = 0.5  # seconds between reads of a request another asker is running
WRAP_UP_AT = 0.7  # share of the Ask timeout after which the source tools ask for the submit
ENDED = ("answered", "failed", "refused")
RECOVER_LIMIT = 1000  # requests read by `recover`
_REF_SPLIT = re.compile(r"[\s,]+")
QUEUED = "The Keeper asked this already; its next review looks."
STILL_RUNNING = "Another question is still searching the archive for this."


class AskArchivistParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["reference", "topic"] = Field(
        description="reference: text names items exactly; topic: text describes what to find."
    )
    text: str = Field(
        min_length=1,
        description=(
            "For reference, the refs as written, separated by spaces: a uid from "
            "unresolved_refs, '#812', a URL, a Linear key. For topic, a few plain words."
        ),
    )
    from_uid: str | None = Field(
        None, description="The brain uid of the item the reference was found in, or null."
    )


TOOL_DESCRIPTION = (
    "Ask the Archivist for items older than the ingest window: an item a brain node refers to "
    "but the brain lacks (get_entity's unresolved_refs), or history on a topic older than the "
    "window. It searches the company's own sources, checks what it finds against the brain and "
    "loads it, so you can cite the finds by uid in this answer. Slow (seconds): use it only "
    "when the item or history is missing. A row with a reason says what it could not reach."
)


class _Tool:
    name = NAME
    description = TOOL_DESCRIPTION
    params = AskArchivistParams


TOOLS = {NAME: _Tool()}


# --- the Ask toolset's hooks ------------------------------------------------------------------


def _never(slug: str) -> bool:
    return False


_building: Callable[[str], bool] = _never


def set_building(check: Callable[[str], bool] | None) -> None:
    """How Ask's runs tell that a company is building (rule 19); the backend sets it (None:
    never building)."""
    global _building
    _building = check or _never


def building(slug: str) -> bool:
    return _building(slug)


# --- one call ---------------------------------------------------------------------------------


def refs_of(kind: str, text: str) -> list[str]:
    """The exact refs of a reference request: its text's words, each once, in order."""
    if kind != "reference":
        return []
    return list(dict.fromkeys(r for r in _REF_SPLIT.split(text.strip()) if r))


def run(
    slug: str,
    params: AskArchivistParams,
    *,
    client: Callable[[], anthropic.Anthropic],
    ledger: WorkStore,
    writer: Callable[[dict[str, Any]], None],
    stop: threading.Event | None,
    parent: str | None = None,
    thread: str | None = None,
    building: Callable[[str], bool] = building,
    clock: Callable[[], float] = time.monotonic,
    poll: float = POLL,
) -> list[dict[str, Any]]:
    """One `ask_archivist` call; its one row. `client()` makes the Archivist's client (only when
    it runs); `writer` is Ask's stream writer and `parent` the Ask tool call id its steps hang
    off; `stop` is the Ask run's stop event."""
    started = clock()
    timeout = get_settings().archivist_ask_timeout

    def timed_out() -> bool:
        return clock() - started > timeout

    def should_stop() -> bool:
        return (stop is not None and stop.is_set()) or timed_out()

    def wrap_up() -> bool:
        return clock() - started >= WRAP_UP_AT * timeout

    created: str | None = None  # the request this call opened, until its run takes it
    try:
        refs = refs_of(params.kind, params.text)
        key = rules.norm(params.kind, params.text, refs)
        if earlier := rules.recall(ledger, key, "ask", utc_now()):
            return [_row(ledger, earlier, reason="remembered", calls=0)]
        opened = {"uid": archive_uid(), "kind": params.kind, "text": params.text, "refs": refs,
                  "from_uid": params.from_uid, "asked_by": "ask", "thread": thread,
                  "norm": key, "now": utc_now()}  # fmt: skip
        [row] = ledger.write("ledger/archive_open_request", WRITER, opened)
        created = row["uid"] if row["created"] else None
        request = _get(ledger, row["uid"])
        if request is None:
            raise LookupError(f"{row['uid']} could not be read back")
        if not created:
            if request.asked_by == "keeper" and request.status == "open":
                return [_row(ledger, request, reason="queued", summary=QUEUED)]
            return [_join(ledger, request, should_stop, timed_out, poll)]

        # Ask's writer reads Ask's run from the context it is called in, so it is called in a
        # copy of Ask's (taken here, before the switch).
        ask_ctx = contextvars.copy_context()

        def forward(chunk: dict[str, Any]) -> None:
            body = {k: v for k, v in chunk.items() if k != "kind"}
            step = {**body, "kind": "archive_step", "parent": parent, "event": chunk.get("kind")}
            ask_ctx.run(writer, step)

        archivist = client()
        created = None  # answer_request never raises: it ends the request itself
        # An empty context: LangGraph must not see Ask's run as this run's parent.
        done = contextvars.Context().run(
            answer_request, ledger, slug, request, client=archivist, tier="ask",
            on_event=forward, should_stop=should_stop, wrap_up=wrap_up, building=building,
        )  # fmt: skip
        stopped = stop is not None and stop.is_set()
        late = done.partial and not stopped and (timed_out() or wrap_up())
        return [_row(ledger, done, reason="timeout" if late else done.reason)]
    except Exception as e:  # never raised: Ask answers with what it has
        _log.warning("ask_archivist failed for %s", slug, exc_info=True)
        reason = f"error: {type(e).__name__}: {e}"[:300]
        if created:  # opened but never run: end it, or its question stays blocked (rule 16)
            _abandon(ledger, created, reason)
        return [_failed(created, reason)]


def _join(
    ledger: WorkStore,
    request: ArchiveRequest,
    should_stop: Callable[[], bool],
    timed_out: Callable[[], bool],
    poll: float,
) -> dict[str, Any]:
    """Rule 16: another asker runs this question; wait for its answer within the Ask timeout."""
    while request.status not in ENDED:
        if should_stop():
            reason = "timeout" if timed_out() else "stopped"
            return _row(ledger, request, reason=reason, summary=STILL_RUNNING)
        time.sleep(poll)
        request = _get(ledger, request.uid) or request
    return _row(ledger, request)


def _abandon(ledger: WorkStore, uid: str, reason: str) -> None:
    try:
        ledger.write("ledger/archive_set_request", WRITER, {"uid": uid, "from": ["open"],
                     "to": "failed", "reason": reason, "now": utc_now()})  # fmt: skip
    except Exception:
        _log.warning("could not end %s", uid, exc_info=True)


def _get(ledger: WorkStore, uid: str) -> ArchiveRequest | None:
    rows = ledger.read("ledger/archive_get_request", {"uid": uid})
    return ArchiveRequest(**rows[0]) if rows else None


def _row(
    ledger: WorkStore,
    request: ArchiveRequest,
    *,
    reason: str | None = None,
    summary: str | None = None,
    calls: int | None = None,
) -> dict[str, Any]:
    """The tool's row for a request: its outcome and its finds (`uid` makes them citable).
    `calls`: the external calls this turn caused (default: the request's)."""
    finds = []
    if request.status == "answered":
        for f in ledger.read("ledger/archive_finds", {"requests": [request.uid]}):
            finds.append({"uid": f["uid"], "title": f.get("title"), "url": f.get("url"),
                          "date": f.get("date"), "verdict": f.get("verdict"),
                          "superseded_by": f.get("superseded_by"), "archived": True})  # fmt: skip
    return {
        "request": request.uid,
        "status": request.status,
        "outcome": request.outcome,
        "summary": summary or request.summary,
        "partial": request.partial,
        "reason": reason if reason is not None else request.reason,
        "calls": request.calls if calls is None else calls,
        "finds": finds,
    }


def _failed(uid: str | None, reason: str) -> dict[str, Any]:
    return {"request": uid, "status": "failed", "outcome": None, "summary": None,
            "partial": False, "reason": reason, "calls": 0, "finds": []}  # fmt: skip


# --- startup ----------------------------------------------------------------------------------


def recover(ledger: WorkStore) -> int:
    """Ask's requests a restart cut off: every one still `running` (its Ask run is gone) and
    every one still `open` (nothing but an Ask run takes an Ask request, and the open one would
    keep its question from opening again) becomes `failed`, reason `restart`. The Keeper's are
    left to its reviews. Returns how many moved."""
    rows = ledger.read("ledger/archive_requests",
                       {"statuses": ["open", "running"], "limit": RECOVER_LIMIT})  # fmt: skip
    n = 0
    for r in (ArchiveRequest(**r) for r in rows):
        if r.asked_by != "ask":
            continue
        moved = {"uid": r.uid, "from": [r.status], "to": "failed", "reason": "restart",
                 "calls": r.calls, "now": utc_now()}  # fmt: skip
        if ledger.write("ledger/archive_set_request", WRITER, moved):
            n += 1
    return n
