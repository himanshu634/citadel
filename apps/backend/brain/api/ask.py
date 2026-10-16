"""Ask route: one question to a company's brain, answered as Server-Sent Events.

Why: the Ask page draws the agent's walk through the graph while it happens (design direction D,
"Watch it walk"). POST /api/companies/{slug}/ask runs `agents.ask.ask_events` in a worker thread
and forwards each event as it comes: `start`, then `step` / `step_done` per tool call, then
`answer`, or `error` with a sentence when the run fails. Payloads are the Ask* models.

- The run is checkpointed per thread (graph agent_<slug>); `thread_id` in the body asks a
  follow-up. One run per thread at a time (409).
- When the browser goes away (or presses Stop, which closes the stream), the run stops at its
  next step and the thread stays valid for the next question.
- The worker is a plain thread, not the request's task: a cancelled request only asks it to stop.
- Every turn leaves a trace (`agents/traces.py`, data/traces/<slug>.jsonl), written by the worker
  before the `answer` event goes out, so a stopped turn is kept too and a thumbs click
  (`api/traces.py`) always finds it. The event carries its `trace_id`; None when the write failed.
- Every turn is also kept in the chat history (`agents/history.py`, graph agent_<slug>) as it
  runs: each event is recorded after it is sent, `start` and the answer before, so the chat
  list has the chat as soon as the page knows its id, and a reload right after the answer finds
  it done (`api/threads.py`). Each Claude response goes out as an
  `llm` event (its text, thinking and the tools it asked for, MCP calls included).
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sse_starlette import EventSourceResponse

from brain import db, llm
from brain.agents.ask import Answer, answer_out, run_events
from brain.agents.history import ChatStore, GraphChatStore, Recorder
from brain.agents.toolset import Toolset, graph_toolset
from brain.agents.traces import TraceStore, new_trace
from brain.api.deps import company_slug
from brain.api.models import AskAnswer, AskError, AskIn, AskLlm, AskStart, AskStep, AskStepDone

log = logging.getLogger(__name__)
router = APIRouter(tags=["ask"])

PING_SECONDS = 15
CLAIM_WAIT_SECONDS = 60.0  # how long a follow-up waits for its thread's stopped run to end
Slug = Annotated[str, Depends(company_slug)]

_MODELS: dict[str, type[BaseModel]] = {
    "start": AskStart,
    "llm": AskLlm,
    "step": AskStep,
    "step_done": AskStepDone,
    "answer": AskAnswer,
    "error": AskError,
}


@dataclass
class Asker:
    """What a run needs, on app.state so tests can hand in a scripted Claude and fake tools."""

    client: Callable[[], Any] = llm.client
    toolset: Callable[[], Toolset] = graph_toolset
    checkpointer: Callable[[str], Any] = db.checkpointer
    graph_exists: Callable[[str], bool] = db.graph_exists
    traces: Callable[[str], TraceStore] = TraceStore
    history: Callable[[str], ChatStore] = lambda slug: graph_history(slug)  # noqa: E731
    claim_wait: float = CLAIM_WAIT_SECONDS
    _busy: set[str] = field(default_factory=set)
    _free: threading.Condition = field(default_factory=threading.Condition)

    def claim(self, thread_id: str) -> bool:
        """Take the thread for a run. A thread still finishing a stopped run (its Claude call in
        flight) is waited for, so Stop and then a follow-up does not bounce."""
        with self._free:
            if not self._free.wait_for(lambda: thread_id not in self._busy, self.claim_wait):
                return False
            self._busy.add(thread_id)
            return True

    def release(self, thread_id: str) -> None:
        with self._free:
            self._busy.discard(thread_id)
            self._free.notify_all()

    def busy(self, thread_id: str) -> bool:
        with self._free:
            return thread_id in self._busy


def graph_history(slug: str) -> ChatStore:
    """The history store a default Asker uses (looked up at call time, so tests can swap it)."""
    return GraphChatStore(slug)


def get_asker(request: Request) -> Asker:
    return request.app.state.asker


@router.post("/companies/{slug}/ask")
def ask(slug: Slug, body: AskIn, asker: Annotated[Asker, Depends(get_asker)]):
    if not asker.graph_exists(slug):
        raise HTTPException(status_code=409, detail=f"{slug} has no graph yet. Build it, then ask.")
    thread_id = body.thread_id or uuid.uuid4().hex[:12]
    if not asker.claim(thread_id):
        raise HTTPException(
            status_code=409,
            detail="This chat is still answering. Wait for it, or start a new chat.",
        )
    return EventSourceResponse(_events(asker, slug, body.question, thread_id), ping=PING_SECONDS)


async def _events(asker: Asker, slug: str, question: str, thread_id: str) -> AsyncIterator[dict]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    stop = threading.Event()

    def put(item: dict | None) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, item)
        except RuntimeError:  # the server's loop is gone (shutdown): nobody is listening
            pass

    def work() -> None:
        started = time.perf_counter()
        steps: list[dict] = []
        recorder = Recorder(asker.history(slug), question)

        def keep(answer: Answer | None = None, error: str | None = None) -> str | None:
            ms = round((time.perf_counter() - started) * 1000)
            trace = new_trace(
                slug, question, thread_id, via="api", steps=steps, ms=ms, answer=answer, error=error
            )
            return trace.id if asker.traces(slug).add(trace) else None

        try:
            for event in run_events(
                slug,
                question,
                thread_id,
                client=asker.client(),
                toolset=asker.toolset(),
                checkpointer=asker.checkpointer(slug),
                stop=stop,
            ):
                if isinstance(event, Answer):
                    payload = answer_out(event, keep(event))
                    recorder.answer(payload, event.model)
                    put(payload)
                    continue
                if event.get("kind") == "step_done":
                    steps.append(dict(event))  # the sender pops "kind" from the original
                record = dict(event)  # likewise
                if record["kind"] == "start":
                    recorder.on(record)  # before the page hears of it, so its chat list has it
                    put(event)
                else:
                    put(event)
                    recorder.on(record)
        except Exception as exc:
            problem = llm.describe_error(exc)
            if problem is None:
                log.exception("ask %s failed", slug)
                problem = f"The answer failed: {type(exc).__name__}: {exc}"
            recorder.fail(problem, keep(error=problem))
            put({"kind": "error", "detail": problem})
        finally:
            asker.release(thread_id)
            put(None)

    threading.Thread(target=work, name=f"ask-{slug}-{thread_id}", daemon=True).start()
    try:
        while (event := await queue.get()) is not None:
            kind = event.pop("kind")
            payload = _MODELS[kind].model_validate(event)
            yield {"event": kind, "data": payload.model_dump_json()}
    finally:
        stop.set()  # the browser left or the run ended: either way, nothing more to do
