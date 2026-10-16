# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Company Brain: turns a company's public engineering activity into one FalkorDB graph per company
(`brain_<slug>`) that agents can query, with sources and graph paths behind every answer. Entry for
*Graph Hacks: Context for AI Agents* (FalkorDB × WeMakeDevs). Monorepo: a uv workspace for the
Python backend (`apps/backend`, package `brain`, CLI `brain`) and a pnpm SvelteKit app
(`apps/frontend`).

## Commands

Everything goes through the Makefile (`make help`). Company-scoped targets take `SLUG=<slug>`
(default `falkordb`; configs live in `companies/<slug>.yaml`).

```bash
make setup                     # uv sync + create .env from .env.example
make up / make down            # FalkorDB in Docker (:6379, Browser UI on :3000)
make schema SLUG=synthetic     # create indexes on brain_synthetic (idempotent)
make synthetic                 # regenerate synthetic JSONL, schema + full ingest into brain_synthetic
make fetch | ingest | sync     # SOURCE=<type> limits to one source; FULL=1 ignores sync cursors
make stats                     # node/relationship counts
make tools                     # list the named query tools and their params
make query TOOL=impact_of P="system=CI"   # run one (SLUG=..., JSON=1 for raw rows)
make reset SLUG=x CONFIRM=1    # delete a company graph
make brain ARGS="..."          # any `brain` CLI command

make lint                      # ruff check + format --check (line length 100, py312)
make fmt                       # ruff format + autofix
make test                      # pytest apps/backend/tests (graph tests need `make up`)
make test ARGS="apps/backend/tests/test_x.py::test_y"   # single test

make fe-install | fe-dev | fe-check | fe-build   # frontend: pnpm install, dev on :5173, svelte-check, static build
```

Configuration comes from `.env` (see `.env.example`): FalkorDB host/port/credentials and
`FALKORDB_TLS` (the same code runs against local Docker or FalkorDB Cloud), `GITHUB_TOKEN`
(falls back to `gh auth token`), and Vertex AI embedding settings. `EMBEDDING_DIM` must match the
embedding model because the vector index is created with it.

## Backend architecture (`apps/backend/brain`)

Ingestion is a one-way pipeline; each stage knows only the one next to it:

```
companies/<slug>.yaml ─► adapter.fetch  ─► data/raw/<slug>/<type>/   (network, cached)
                         adapter.records ─► CanonicalRecord          (pure transform, no network)
                         normalize       ─► company rules applied    (pure)
                         loader          ─► MERGE into brain_<slug>  (only writer to FalkorDB)
```

- **`canonical.py`** is the contract between adapters and the loader (Person, Team, System,
  WorkItem, Change, Document, Comment, Review, Ownership, Link). Every record has a stable `uid`;
  people/teams/systems use source-free uids (`person:<login>`, `team:<name>`, `system:<name>`) so
  the same entity from two sources becomes one node. No email addresses anywhere: people are
  identified by login. `WorkItem.kind` covers PRs, issues, tickets and chat threads.
- **`adapters/`**: one module (or package) per source type, defining the adapter and its
  `SourceConfig` subclass, plus one line in `adapters/__init__.py`'s `REGISTRY`; `CompanyConfig`
  validates each `sources:` entry through the registry. Copy `adapters/_template.py`. `fetch` does all network
  I/O into the cache; `records` must read only the cache or local files, so re-ingest costs no API
  calls. Raise `SourceUnavailable` to make ingest skip a source.
- **`normalize.py`** applies the company YAML: path → System rules (first match wins, then
  `fallback`, `ignore`), bot detection and login aliases, conventional-commit prefix →
  `Change.kind`, email scrubbing, the `window.since` cutoff (a work item needs real activity in
  the window: created/closed/merged, or a comment/review; a bare `updated_at` bump does not
  count), and synthesising any referenced person/team/system that has no record. Keep it pure.
- **`adapters/github/`**: `fetch.py` (GraphQL pages in resumable "runs" + a blob-less partial
  clone for commit file lists + CODEOWNERS/doc texts; refuses private repos unless
  `data_permission: own`), `transform.py` (cache → records; only completed runs are read),
  GraphQL documents in `queries/*.graphql`. Tests use recorded pages in
  `tests/fixtures/github/`.
- **`loader.py`** batches rows (`UNWIND $rows`, 500 per query) into `queries/load/*.cypher`. All
  writes are `MERGE` on uid then `SET`, so loads are idempotent. Nodes are written before
  relationships; relationship queries `MATCH` both ends, so dangling links are dropped and counted.
- **`pipeline.py`** is the source-agnostic glue the CLI calls. Ingest is incremental: each source
  has a `SyncState` node holding a cursor; records older than it are skipped, records without a
  timestamp (people, teams, ownership, links) are always loaded. `--full` ignores the cursor.
- **`tools.py`** is the read side: `TOOLS` maps each tool name to its `queries/tools/<name>.cypher`,
  a pydantic params model (input schema for agents) and a row model (always uids + urls for
  citations). `call(slug, name, **params)` is the one entry point; typed wrappers sit on top.
  `prepare` only converts params (days → epoch, text → RediSearch OR query, login → uid). No
  LLM-generated Cypher anywhere. `path_between` uses `algo.SPpaths` (FalkorDB's `shortestPath`
  rejects undirected traversals).
- **`db.py`** is the only place that opens a connection and selects the graph (`brain_<slug>`);
  all queries go through `db.run()` so nothing can hit the wrong company's graph.

### Named Cypher queries

Python never holds Cypher strings. Every query lives in `apps/backend/queries/<folder>/<name>.cypher`
with a leading `//` header (purpose / params / returns) and is fetched by name via
`queries.get("load/person")`. A file may hold several statements separated by `;` (FalkorDB runs one
statement per `GRAPH.QUERY`), which the schema files use. Folders: `schema/` (range, full-text,
vector indexes, applied in order by `schema.py`, "already indexed" errors are skipped), `load/`
(loader writes), `tools/` (agent-facing read queries).

The synthetic company (`apps/backend/examples/synthetic_company`, source type `canonical_jsonl`)
is a small offline dataset for demos and tests; its JSONL is generated by `generate.py`.

## Frontend architecture (`apps/frontend`)

SvelteKit 2 + Svelte 5 runes + TypeScript, bits-ui primitives, Lucide icons. Built with
`adapter-static` (SPA fallback `200.html`, everything prerendered). It will read from the backend
over HTTP, never from FalkorDB directly; until that API exists, pages use `src/lib/data/sample.ts`
(shapes in `src/lib/types.ts` — keep them when swapping in API calls).

`apps/frontend/design-system.md` is the rulebook ("Wide type, calm body"). Rules that bite:
- Components read tokens only (`src/lib/styles/tokens.css`); no literal colours, sizes or radii in
  components.
- When code and `design-system.md` disagree, fix one of them in the same change.
- New components are exported from `src/lib/index.ts` and shown with their states in the
  `/components` gallery. Check both themes.

Components are split into `ui/` (generic), `brain/` (answer and graph patterns) and `layout/`
(app frame). `.claude/launch.json` defines the `frontend` preview server on port 5173.
