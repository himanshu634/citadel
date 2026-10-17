"""Agent activity: the Systems page's runs, newest first, each with its steps on the graph.

Why: the Systems page draws where an agent is working and the trail of nodes it touched. Today
the runs are Ask turns, read from the chat history (`agents/activity.py` has the shape and why);
Keeper reviews will join the same list.

- GET .../activity?limit= : the latest runs across the most recently active chats, newest first,
  and whether one is still running. A turn left `running` by a server that went away is shown as
  stopped, as in the chat routes, since no run can finish it.
"""

from __future__ import annotations

from typing import Annotated

from agents.activity import Activity, runs_from_thread
from agents.history import NEVER
from fastapi import APIRouter, Depends, Query

from backend.api.ask import Asker, get_asker
from backend.api.deps import company_slug

router = APIRouter(prefix="/companies/{slug}", tags=["activity"])
Slug = Annotated[str, Depends(company_slug)]
AskerDep = Annotated[Asker, Depends(get_asker)]


@router.get("/activity")
def activity(
    slug: Slug,
    asker: AskerDep,
    limit: Annotated[int, Query(ge=1, le=20)] = 6,
) -> Activity:
    history = asker.history(slug)
    runs = []
    # A run is a turn; each of the latest `limit` chats holds at least one, which is enough.
    for summary in history.list_threads(NEVER, limit):
        thread = history.get_thread(summary.id)
        if thread is None:  # deleted between the two reads
            continue
        live = asker.busy(thread.id)
        for run in runs_from_thread(thread):
            if run.status == "running" and not live:
                run.status = "stopped"
            runs.append(run)
    runs.sort(key=lambda r: r.started_at, reverse=True)
    runs = runs[:limit]
    return Activity(runs=runs, running=any(r.status == "running" for r in runs))
