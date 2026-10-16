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
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sse_starlette import EventSourceResponse

from brain import db, llm
from brain.agents.ask import ask_events
from brain.agents.toolset import Toolset, graph_toolset
from brain.api.deps import company_slug
from brain.api.models import AskAnswer, AskError, AskIn, AskStart, AskStep, AskStepDone

log = logging.getLogger(__name__)
router = APIRouter(tags=["ask"])

PING_SECONDS = 15
Slug = Annotated[str, Depends(company_slug)]

_MODELS: dict[str, type[BaseModel]] = {
    "start": AskStart,
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
    _busy: set[str] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def claim(self, thread_id: str) -> bool:
        with self._lock:
            if thread_id in self._busy:
                return False
            self._busy.add(thread_id)
            return True

    def release(self, thread_id: str) -> None:
        with self._lock:
            self._busy.discard(thread_id)


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
        try:
            for event in ask_events(
                slug,
                question,
                thread_id,
                client=asker.client(),
                toolset=asker.toolset(),
                checkpointer=asker.checkpointer(slug),
                stop=stop,
            ):
                put(event)
        except Exception as exc:
            problem = llm.describe_error(exc)
            if problem is None:
                log.exception("ask %s failed", slug)
                problem = f"The answer failed: {type(exc).__name__}: {exc}"
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
