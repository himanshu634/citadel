"""HTTP API for the frontend: `app` is what uvicorn serves (`brain.api:app`).

Why: the frontend never reads FalkorDB or the YAML files directly. Routes sit under /api and
are scoped by company slug; CORS opens only the Vite dev server. The app owns one job runner;
at startup it marks builds that a previous server process left unfinished as stopped.
"""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from brain.api import ask, builds, checks, companies, graph, onboard, overview, tools
from brain.api.ask import Asker
from brain.jobs import JobRunner

DEV_ORIGIN = "http://localhost:5173"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.runner.recover()
    yield


def create_app(runner: JobRunner | None = None, asker: Asker | None = None) -> FastAPI:
    app = FastAPI(title="Company Brain", lifespan=lifespan)
    app.state.runner = runner or JobRunner()
    app.state.start_lock = threading.Lock()
    app.state.asker = asker or Asker()
    app.add_middleware(CORSMiddleware, allow_origins=[DEV_ORIGIN], allow_methods=["*"])

    @app.exception_handler(RedisConnectionError)
    @app.exception_handler(RedisTimeoutError)  # a host that does not answer (connect timeout)
    async def graph_down(_: Request, exc: RedisConnectionError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "FalkorDB is not reachable"})

    app.include_router(companies.router, prefix="/api")
    app.include_router(builds.router, prefix="/api")
    app.include_router(checks.router, prefix="/api")
    app.include_router(onboard.router, prefix="/api")
    app.include_router(overview.router, prefix="/api")
    app.include_router(tools.router, prefix="/api")
    app.include_router(ask.router, prefix="/api")
    app.include_router(graph.router, prefix="/api")
    return app


app = create_app()
