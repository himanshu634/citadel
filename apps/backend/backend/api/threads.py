"""Chat history routes: the Ask page's list of past chats, one chat reopened, and delete.

Why: every Ask turn is kept in graph agent_<slug> as it runs (`agents/history.py`). These routes
read it back. The list is shared by everyone who opens the company (there are no users yet).

- GET .../threads?before=&limit= : chats, most recently active first; `next` pages on.
- GET .../threads/{id} : every turn with its Claude responses, tool calls and answer, and the
  thumbs on each answer (from its trace). A turn left `running` by a server that went away is
  shown as stopped, since no run can finish it.
- GET .../refs/{uid}/threads : the chats that touched or cited one node of the company graph.
- DELETE .../threads/{id} : the history and the thread's checkpoints (409 while it answers).
"""

from __future__ import annotations

from typing import Annotated

from agents.history import NEVER, Thread, ThreadPage, ThreadSummary
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response

from backend.api.ask import Asker, get_asker
from backend.api.deps import company_slug

router = APIRouter(prefix="/companies/{slug}", tags=["threads"])
Slug = Annotated[str, Depends(company_slug)]
ThreadId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
AskerDep = Annotated[Asker, Depends(get_asker)]
CUT_OFF = "The answer ended before it finished."


@router.get("/threads")
def list_threads(
    slug: Slug,
    asker: AskerDep,
    before: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> ThreadPage:
    rows = asker.history(slug).list_threads(before or NEVER, limit + 1)
    page = [_live(asker, t) for t in rows[:limit]]
    last = page[-1].updated_at if len(rows) > limit else None
    return ThreadPage(threads=page, next=int(last.timestamp() * 1000) if last else None)


@router.get("/threads/{thread_id}")
def get_thread(slug: Slug, thread_id: ThreadId, asker: AskerDep) -> Thread:
    thread = asker.history(slug).get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail=f"No chat {thread_id} for {slug}")
    running = asker.busy(thread_id)
    for turn in thread.turns:
        if turn.status == "running" and not running:
            turn.status, turn.error = "stopped", CUT_OFF
    if thread.last_status == "running" and not running:
        thread.last_status = "stopped"
    ratings = {
        t.id: t.feedback
        for t in asker.traces(slug).read()
        if t.thread_id == thread_id and t.feedback is not None
    }
    for turn in thread.turns:
        trace_id = (turn.answer or {}).get("trace_id")
        if trace_id in ratings:
            turn.rating, turn.note = ratings[trace_id].rating, ratings[trace_id].note
    return thread


@router.get("/refs/{uid:path}/threads")
def ref_threads(
    slug: Slug,
    uid: Annotated[str, Path(min_length=1, max_length=300)],  # doc uids hold slashes
    asker: AskerDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[ThreadSummary]:
    return [_live(asker, t) for t in asker.history(slug).ref_threads(uid, limit)]


@router.delete("/threads/{thread_id}", status_code=204)
def delete_thread(slug: Slug, thread_id: ThreadId, asker: AskerDep) -> Response:
    if asker.busy(thread_id):
        raise HTTPException(status_code=409, detail="This chat is still answering. Stop it first.")
    if not asker.history(slug).delete_thread(thread_id):
        raise HTTPException(status_code=404, detail=f"No chat {thread_id} for {slug}")
    saver = asker.checkpointer(slug)
    if saver is not None:
        saver.delete_thread(thread_id)
    return Response(status_code=204)


def _live(asker: Asker, t: ThreadSummary) -> ThreadSummary:
    if t.last_status == "running" and not asker.busy(t.id):
        return t.model_copy(update={"last_status": "stopped"})
    return t
