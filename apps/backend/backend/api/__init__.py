"""HTTP API for the frontend: `app` is what uvicorn serves (`backend.api:app`).

Why: the frontend never reads FalkorDB or the YAML files directly. Routes sit under /api and
are scoped by company slug; CORS opens only the Vite dev server. The app owns one job runner and
one set of Keeper review runs, wired together: a build that finishes `done` starts a Keeper
review (budget `keeper_build_budget`; kept pending when a review is running), the Keeper refuses
to review or decide while the company builds (`runner.building`), and a rebuild stops the
company's review before it drops the graph. At startup it marks builds and Keeper reviews that
a previous server process left unfinished as stopped.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
from agents.archivist import live as archivist_live
from brain.config import get_settings
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from backend import keeper_runs, registry
from backend.api import (
    activity,
    archive,
    ask,
    builds,
    checks,
    companies,
    graph,
    onboard,
    overview,
    sources,
    threads,
    tools,
    traces,
)
from backend.api import keeper as keeper_routes
from backend.api.ask import Asker
from backend.jobs import JobRunner
from backend.keeper_runs import KeeperRuns

log = logging.getLogger(__name__)

DEV_ORIGIN = "http://localhost:5173"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.runner.recover()
    try:
        await anyio.to_thread.run_sync(app.state.keeper.recover)
    except Exception:  # best effort: a review left `running` only blocks the next one
        log.warning("could not recover the Keeper reviews", exc_info=True)
    await anyio.to_thread.run_sync(recover_archive_requests)
    yield


def recover_archive_requests() -> None:
    """Ask's archive requests a restart cut off become failed (`archivist.live.recover`). Best
    effort per company: one without a ledger is skipped."""
    for company in registry.list_companies():
        try:
            moved = archivist_live.recover(keeper_runs.keeper_store(company.slug))
            if moved:
                log.info("marked %d archive requests of %s failed (restart)", moved, company.slug)
        except Exception:
            log.warning("could not recover the archive requests of %s", company.slug,
                        exc_info=True)  # fmt: skip


def create_app(
    runner: JobRunner | None = None, asker: Asker | None = None, keeper: KeeperRuns | None = None
) -> FastAPI:
    """The app. A `runner` handed in without an `on_done` / `before_reset` gets them here: after
    each build that ends `done`, `keeper` (default: a new KeeperRuns) starts a review of that
    company; before a rebuild drops a graph, it stops that company's review. `keeper` reads
    `runner.building`."""
    app = FastAPI(title="Company Brain", lifespan=lifespan)
    runs = keeper or KeeperRuns()

    def review_after_build(slug: str) -> None:
        runs.start(slug, trigger="build", budget=get_settings().keeper_build_budget)

    runner = runner or JobRunner(on_done=review_after_build)
    if runner.on_done is None:
        runner.on_done = review_after_build
    if runner.before_reset is None:
        runner.before_reset = runs.stop_for_rebuild
    runs.building = runner.building
    archivist_live.set_building(runner.building)
    app.state.runner = runner
    app.state.keeper = runs
    app.state.start_lock = threading.Lock()
    app.state.asker = asker or Asker()
    app.add_middleware(CORSMiddleware, allow_origins=[DEV_ORIGIN], allow_methods=["*"])

    @app.exception_handler(RedisConnectionError)
    @app.exception_handler(RedisTimeoutError)  # a host that does not answer (connect timeout)
    async def graph_down(_: Request, exc: RedisConnectionError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "FalkorDB is not reachable"})

    app.include_router(companies.router, prefix="/api")
    app.include_router(activity.router, prefix="/api")
    app.include_router(archive.router, prefix="/api")
    app.include_router(builds.router, prefix="/api")
    app.include_router(checks.router, prefix="/api")
    app.include_router(onboard.router, prefix="/api")
    app.include_router(overview.router, prefix="/api")
    app.include_router(sources.router, prefix="/api")
    app.include_router(tools.router, prefix="/api")
    app.include_router(ask.router, prefix="/api")
    app.include_router(traces.router, prefix="/api")
    app.include_router(threads.router, prefix="/api")
    app.include_router(graph.router, prefix="/api")
    app.include_router(keeper_routes.router, prefix="/api")
    return app


app = create_app()
