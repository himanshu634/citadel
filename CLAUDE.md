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
make up / make down            # FalkorDB in Docker; ports/password from .env (:6379, Browser UI :3000)
make schema SLUG=synthetic     # create indexes on brain_synthetic (idempotent)
make synthetic                 # regenerate synthetic JSONL, schema + full ingest into brain_synthetic
make fetch | ingest | sync     # SOURCE=<type> limits to one source; FULL=1 ignores sync cursors
make stats                     # node/relationship counts
make tools                     # list the named query tools and their params
make query TOOL=impact_of P="system=CI"   # run one (SLUG=..., JSON=1 for raw rows)
make ask SLUG=synthetic Q="who knows Auth?"   # Claude answers from the graph (THREAD=<id> follows up)
make chat SLUG=synthetic OFFLINE=1   # one scripted turn, no API key: router + tools + checkpointer
make agents                    # list the agent roles, their jobs and read tools
make sim SLUG=synthetic SCENARIO=sprint OFFLINE=1   # run the agents (sprint, race, regression)
make reset SLUG=x CONFIRM=1    # delete brain_x, agent_x and its build history (frees the slug)
make brain ARGS="..."          # any `brain` CLI command
make api                       # HTTP API on 127.0.0.1:$API_PORT (default 8000), auto-reload
make dev                       # API + frontend dev server together

make lint                      # ruff check + format --check (line length 100, py312)
make fmt                       # ruff format + autofix
make test                      # pytest apps/backend/tests (graph tests need `make up`)
make test ARGS="apps/backend/tests/test_x.py::test_y"   # single test

make fe-install | fe-dev | fe-check | fe-test | fe-build   # frontend: pnpm install, dev on :5173, svelte-check, vitest, static build
```

Configuration comes from `.env` (see `.env.example`): FalkorDB host/port/credentials and
`FALKORDB_TLS` (the same code runs against local Docker or FalkorDB Cloud), `GITHUB_TOKEN`
(falls back to `gh auth token`). `EMBEDDING_DIM` sets the vector index size and must match
whichever embedding model is used later. `ANTHROPIC_API_KEY`,
`ANTHROPIC_MODEL` (default `claude-haiku-5-5`) and `ANTHROPIC_EFFORT` (default `medium`) drive
`brain ask`.

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
- **API** (`brain/api`, FastAPI; `brain.api:app`, run with `make api`): the frontend's only way in.
  Routes sit under `/api/companies/{slug}/...` (overview, builds, tools); the slug is resolved
  only by `deps.company_slug`, which 404s unless `companies/<slug>.yaml` exists. Behind it:
  `registry.py` (`companies/*.yaml` is the registry; a bad file is reported, not fatal; edits
  round-trip so hand-written comments survive; writes are atomic), `config_diff.py` (says if a
  saved change needs a graph rebuild or a new download), and `jobs.py` (one build per company,
  at most two at once, progress as SSE events, last build kept in `data/jobs/<slug>.json`, a
  build cut off by a restart is marked `stopped`). `/api/onboard/github` adds a company from one
  public GitHub repo (the rail's + dialog): `brain/onboard.py` derives name, slug and window; the
  create re-checks visibility (private repos are refused) and writes and starts under the
  start lock.

### Agents (`brain/agents`)

`brain ask` / `brain chat` run the agent graph (`agents/graph.py`): a `router` hands each turn to
the brain loop; `builder` -> `critic` are placeholders for writing Decision nodes (the router does
not use them yet). The brain loop (`agents/loop.py`): `call_claude` streams one Messages API call
(anthropic SDK via `llm.client()`; `llm.fallback_params` adds server-side `fallbacks: "default"`
for Sonnet/Opus, Haiku has none) and `run_tools` runs the
requested graph tools (`agents/toolset.py` adapts `brain.tools`; never LLM-written Cypher). Rules:
- State is append-only and in Anthropic block format; assistant content is replayed exactly as
  returned (thinking blocks included), because the API rejects edited history. Never trim it.
- All tool results of one turn go back in one user message; failures are `is_error` results.
- The answer comes through the `submit_answer` tool (forced `tool_choice` is a 400 on current
  models). It may cite only uids seen in tool results; anything else is sent back as an error.
- Keep `agents/system_prompt.md` and the tool list static (no dates, sorted tools) so the prompt
  prefix stays cacheable. Threads are checkpointed in graph `agent_<slug>` (`db.checkpointer`).
- Tests use a scripted fake client (`tests/test_agent.py`); nothing in `make test` calls the API.
  `agents/offline.py` is the same idea for `brain chat --offline`.

### Named Cypher queries

Python never holds Cypher strings. Every query lives in `apps/backend/queries/<folder>/<name>.cypher`
with a leading `//` header (purpose / params / returns) and is fetched by name via
`queries.get("load/person")`. A file may hold several statements separated by `;` (FalkorDB runs one
statement per `GRAPH.QUERY`), which the schema files use. Folders: `schema/` (range, full-text,
vector indexes, applied in order by `schema.py`, "already indexed" errors are skipped), `load/`
(loader writes), `tools/` (agent-facing read queries).

The synthetic company (`apps/backend/examples/synthetic_company`, source type `canonical_jsonl`)
is a small offline dataset for demos and tests; its JSONL is generated by `generate.py`.

### Agent roles (`brain/agents/roles`, `brain/work`, `brain/sim`)

The simulated company in [docs/agents.md](docs/agents.md) (the spec; its "Implementation status"
says what is built). Agents never message each other: each reads its queue, makes one decision
and writes it; the next agent finds it through its own queue. Pieces:
- `work/`: the records (`model.py`), every legal task move in one table (`moves.py`: the guard
  each `queries/work/*.cypher` must match), one pydantic model per `submit_*` tool
  (`submits.py`: the write query's params), work-layer read tools (`tools.py`) and the
  `WorkStore` protocol (`store.py`: `read`/`write` by query name, like `db.run`).
  `memory_store.py` is the offline/test double that enforces the same guards; the FalkorDB store
  is phase 2.
- `acl.py`: which database user may read/write which graph (`brain_`, `sim_`, `mem_<slug>_<role>`,
  `agent_`), and which role each writer user acts as. The store refuses what it does not allow.
- `agents/roles/`: one `ROLE` per module (user, sorted read tools, jobs; prompt in
  `agents/prompts/<role>.md` after `_shared.md`). A job = queue read + optional atomic claim +
  one submit tool + `apply` (named writes).
- `agents/runner.py`: runs a job through the brain loop (`loop.py`, parameterised by prompt,
  submit tool and grounding check), then writes and logs one Episode. Read-only roles log to
  their own memory graph.
- `agents/policies/`: a deterministic policy per job; `ScriptedClient` plays it through the real
  loop, so offline runs hit the same checks as Claude. Tests: `test_work_store.py`,
  `test_agent_roles.py` (fake brain in `tests/agent_fakes.py`).
- `sim/`: the orchestrator's tick loop (`STEPS` order) and the scenarios.
Rules: roles cite only uids from this run's tool results; a write that matches nothing changed
nothing; role read tools not yet backed by a query are pinned in `test_tools_still_missing_are_pinned`.

## Frontend architecture (`apps/frontend`)

SvelteKit 2 + Svelte 5 runes + TypeScript, bits-ui primitives, Lucide icons. Built with
`adapter-static` (SPA fallback `200.html`). The static pages are prerendered; `/c/[slug]` and `/new`
are not: they need the live API and the slug at runtime, so the fallback serves them and they render
in the browser. The app reads from the backend over HTTP (the API above), never from FalkorDB
directly (shapes in `src/lib/types.ts`, written by hand to match the API models).

`apps/frontend/design-system.md` is the rulebook ("Wide type, calm body"). Rules that bite:
- Components read tokens only (`src/lib/styles/tokens.css`); no literal colours, sizes or radii in
  components.
- When code and `design-system.md` disagree, fix one of them in the same change.
- New components are exported from `src/lib/index.ts` and shown with their states in the
  `/components` gallery. Check both themes.

Components are split into `ui/` (generic), `brain/` (answer and graph patterns) and `layout/`
(app frame). `.claude/launch.json` defines the `frontend` preview server on port 5173.
