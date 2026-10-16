"""HTTP API for the frontend: `app` is what uvicorn serves (`brain.api:app`).

Why: the frontend never reads FalkorDB or the YAML files directly. Routes sit under /api and
are scoped by company slug; CORS opens only the Vite dev server.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from brain.api import checks, companies

DEV_ORIGIN = "http://localhost:5173"


def create_app() -> FastAPI:
    app = FastAPI(title="Company Brain")
    app.add_middleware(CORSMiddleware, allow_origins=[DEV_ORIGIN], allow_methods=["*"])

    @app.exception_handler(RedisConnectionError)
    @app.exception_handler(RedisTimeoutError)  # a host that does not answer (connect timeout)
    async def graph_down(_: Request, exc: RedisConnectionError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "FalkorDB is not reachable"})

    app.include_router(companies.router, prefix="/api")
    app.include_router(checks.router, prefix="/api")
    return app


app = create_app()
