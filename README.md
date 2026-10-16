# Company Brain

Turns a company's public engineering activity into one FalkorDB graph that agents can query,
with sources and graph paths behind every answer. Entry for *Graph Hacks: Context for AI
Agents* (FalkorDB × WeMakeDevs), tracks **Company Brain** and **Agent Memory & Coordination**.

_Full README (architecture, query table, quick start) lands in step f._

## Monorepo layout

```
apps/backend/    Python 3.12 (uv): ingestion, graph schema, named queries, agents. CLI: `brain`
apps/frontend/   UI (later)
companies/       one YAML config per company -> graph brain_<slug>
docs/            graph model, canonical format, adding a company
data/            gitignored raw API caches and inbox folders
```

## Quick start (so far)

```bash
cp .env.example .env
docker compose up -d          # FalkorDB on :6379, Browser on http://localhost:3000
uv sync
uv run brain schema falkordb  # create indexes on graph brain_falkordb
```
