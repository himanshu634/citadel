"""Agent activity: the Systems page's runs, newest first, each with its steps on the graph.

Why: the Systems page draws where an agent is working and the trail of nodes it touched. The
runs are Ask turns, read from the chat history, and Keeper reviews, read from the ledger
keeper_<slug> with their pm, qa and keeper steps (`agents/activity.py` has the shape and why).

- GET .../activity?limit= : the latest `limit` runs of both kinds, newest first, and whether one
  is still running. A turn or review left `running` by a server that went away is shown as
  stopped, as in the chat routes, since no run can finish it (`Asker.busy`,
  `KeeperRuns.is_running` say what this process runs).
"""

from __future__ import annotations

from typing import Annotated

from agents.activity import Activity, ActivityRun, runs_from_reviews, runs_from_thread
from agents.history import NEVER
from agents.keeper.model import Review, ReviewStep
from fastapi import APIRouter, Depends, Query

from backend.api.ask import Asker, get_asker
from backend.api.deps import company_slug
from backend.api.keeper import Keeper
from backend.keeper_runs import KeeperRuns

router = APIRouter(prefix="/companies/{slug}", tags=["activity"])
Slug = Annotated[str, Depends(company_slug)]
AskerDep = Annotated[Asker, Depends(get_asker)]


@router.get("/activity")
def activity(
    slug: Slug,
    asker: AskerDep,
    keeper: Keeper,
    limit: Annotated[int, Query(ge=1, le=20)] = 6,
) -> Activity:
    runs = _ask_runs(asker, slug, limit) + _review_runs(keeper, slug, limit)
    runs.sort(key=lambda r: r.started_at, reverse=True)
    runs = runs[:limit]
    return Activity(runs=runs, running=any(r.status == "running" for r in runs))


def _ask_runs(asker: Asker, slug: str, limit: int) -> list[ActivityRun]:
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
    return runs


def _review_runs(keeper: KeeperRuns, slug: str, limit: int) -> list[ActivityRun]:
    """The latest `limit` Keeper reviews that are not skipped, and their steps: two reads,
    whatever the limit (the page polls every 1.5 s while a run is going)."""
    store = keeper.store_for(slug)
    reviews = [Review(**r) for r in store.read("ledger/recent_reviews", {"limit": limit})]
    steps: dict[str, list[ReviewStep]] = {r.uid: [] for r in reviews}
    if reviews:
        for row in store.read("ledger/review_steps", {"reviews": list(steps)}):
            step = ReviewStep(**row)
            steps[step.review].append(step)
    return runs_from_reviews(reviews, steps, live=lambda uid: keeper.is_running(slug, uid))
