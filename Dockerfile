# Production images for docker-compose.prod.yml (plan: docs/hosting.md, "The recommended setup").
# Two targets share one build of the frontend:
#   api  the FastAPI backend: one uvicorn worker, no --reload (builds and Keeper reviews are
#        threads in this one process; a second process would stop their work at startup)
#   web  Caddy with the static frontend build; serves the app and proxies /api to `api`

# --- frontend: pnpm build of apps/frontend (static, SPA fallback 200.html) -------------------
FROM node:22-bookworm-slim AS frontend
RUN npm install -g pnpm@11.2.2
WORKDIR /src/apps/frontend
COPY apps/frontend/package.json apps/frontend/pnpm-lock.yaml apps/frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY apps/frontend/ ./
RUN pnpm build

# --- api: Python 3.12 + uv, the three workspace packages --------------------------------------
FROM python:3.12-slim-bookworm AS api
COPY --from=ghcr.io/astral-sh/uv:0.11.17 /uv /usr/local/bin/uv
# git: the GitHub adapter makes a blob-less partial clone for commit file lists.
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY apps/brain/pyproject.toml apps/brain/pyproject.toml
COPY apps/agents/pyproject.toml apps/agents/pyproject.toml
COPY apps/backend/pyproject.toml apps/backend/pyproject.toml
# Third-party dependencies first, so a code change does not reinstall them.
RUN uv sync --frozen --no-dev --no-install-workspace
# The workspace packages install editable: brain reads its Cypher from apps/brain/queries.
COPY apps/brain apps/brain
COPY apps/agents apps/agents
COPY apps/backend apps/backend
RUN rm -rf apps/brain/tests apps/agents/tests apps/backend/tests \
    && uv sync --frozen --no-dev
COPY companies companies
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

# BRAIN_ROOT is the volume that holds companies/ and data/ (docker-entrypoint seeds it). It is
# created here, owned by the app user, so an empty named volume mounts writable.
RUN useradd --create-home --uid 10001 citadel \
    && mkdir -p /srv/citadel && chown citadel:citadel /srv/citadel
USER citadel
ENV PATH=/app/.venv/bin:$PATH BRAIN_ROOT=/srv/citadel PYTHONUNBUFFERED=1
EXPOSE 8000
ENTRYPOINT ["entrypoint.sh"]
CMD ["uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]

# --- web: Caddy + the static build -----------------------------------------------------------
FROM caddy:2.10.2-alpine AS web
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=frontend /src/apps/frontend/build /srv/www
