# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Company Brain: turns a company's public engineering activity into one FalkorDB graph per company
(`brain_<slug>`) that agents can query, with sources and graph paths behind every answer. Entry for
*Graph Hacks: Context for AI Agents* (FalkorDB × WeMakeDevs). Monorepo: a uv workspace of three
Python packages and a pnpm SvelteKit app (`apps/frontend`):

| Folder | Package · CLI | Holds |
|---|---|---|
| `apps/brain` | `brain` · `brain` | the engine: adapters, pipeline, loader, schema, queries, named tools, `db.py`, `graph_view.py` |
| `apps/agents` | `agents` · `agents` | Claude agents, roles, work store, sim, evals, traces; reach the graph only through named tools |
| `apps/backend` | `backend` · `backend` | FastAPI app (`backend.api:app`), jobs, registry, onboard, config diff |

Dependency rule: backend → agents → brain, never the reverse. Diagram: `docs/architecture/`.

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
make ask SLUG=synthetic Q="who knows Auth?"   # `agents ask`: Claude answers from the graph (THREAD=<id> follows up)
make chat SLUG=synthetic OFFLINE=1   # `agents chat`: one scripted turn, no API key: router + tools + checkpointer
make eval                      # agent evals on brain_synthetic (calls the API): CASE=id|tag REPEAT=3 MODEL=.. EFFORT=.. BASELINE=<file>
make traces SLUG=x DAYS=7      # live Ask traffic: no-answer/step-limit/nudge/... rates, p50/p95 latency and tokens, thumbs
make eval-drafts SLUG=x        # thumbs-down answers as draft eval cases (WRITE=1 appends to evals/cases/x.yaml)
make chats-backfill SLUG=x     # chat history for threads asked before it existed (checkpoints + traces; ALL=1 adds untraced)
make keeper-review SLUG=synthetic OFFLINE=1   # one Keeper review (scripted jobs, no key; BUDGET=n gaps)
make keeper-notice SLUG=x      # open gaps for what brain_x shows on its own (stale owners, unowned busy systems)
make keeper-gaps SLUG=x STATUS=open   # the Keeper's gaps;  make keeper-log SLUG=x LIMIT=20: its log
# also `agents keeper claims|approve|reject SLUG [CLAIM --by NAME --why ...]` (uv run agents keeper --help)
make agents                    # list the agent roles, their jobs and read tools
make sim SLUG=synthetic SCENARIO=sprint OFFLINE=1   # run the simulation (sprint, race, regression); not the product story
make reset SLUG=x CONFIRM=1    # delete brain_x, agent_x, keeper_x, its build history and Ask traces (frees the slug)
make linear-seed SLUG=synthetic_linear CONFIRM=1   # copy the synthetic tickets into a real Linear workspace
make brain ARGS="..."          # any `brain` CLI command
make api                       # HTTP API on 127.0.0.1:$API_PORT (default 8000), auto-reload
make dev                       # API + frontend dev server together

make lint                      # ruff check + format --check (line length 100, py312)
make fmt                       # ruff format + autofix
make test                      # pytest apps/{brain,agents,backend}/tests (graph tests need `make up`)
make test ARGS="apps/brain/tests/test_x.py::test_y"   # single test

make fe-install | fe-dev | fe-check | fe-test | fe-build   # frontend: pnpm install, dev on :5173, svelte-check, vitest, static build
```

Configuration comes from `.env` (see `.env.example`): FalkorDB host/port/credentials and
`FALKORDB_TLS` (the same code runs against local Docker or FalkorDB Cloud), `GITHUB_TOKEN`
(falls back to `gh auth token`). `EMBEDDING_DIM` sets the vector index size and must match
whichever embedding model is used later. `ANTHROPIC_API_KEY`,
`ANTHROPIC_MODEL` (default `claude-haiku-5-5`) and `ANTHROPIC_EFFORT` (default `medium`) drive
`agents ask` and the Keeper's jobs. `KEEPER_BUDGET` (5, gaps one on-demand review decides),
`KEEPER_BUILD_BUDGET` (3, the review after a build) and `KEEPER_NOTICE_CAP` (10, max new gaps per
noticing run) tune the Keeper. Settings live in `brain/config.py` (also `REPO_ROOT`).

## Brain architecture (`apps/brain/brain`)

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
  validates each `sources:` entry through the registry. Copy `adapters/_template.py`. `fetch` does
  all network I/O into the cache; `records` must read only the cache or local files, so re-ingest costs no API
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
- **`adapters/runs.py`**: the resumable, incremental paging into a raw cache that GitHub and
  Linear share (`fetch_paged`, `completed_pages`).
- **`adapters/linear/`** (`LINEAR_API_KEY`; `own`/`synthetic` data only): `client.py`, `fetch.py`,
  `transform.py`, `seed.py` (`make linear-seed`, the only writer to Linear). Issues become
  WorkItem `kind: ticket`; ASSIGNED_TO is replaced on every load, BLOCKS edges of the source
  missing from a load are pruned (`origin`), attachment URLs become MENTIONS resolved by url.
  Tests use the hand-written cache in `tests/fixtures/linear/`.
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
- **`graph_view.py`** builds the Graph page's view: every drawable node and link, and the
  territory (home system) of each node; the rules are in its module doc. Pure apart from `load`.
- **`db.py`** is the only place that opens a connection and selects the graph (`brain_<slug>`);
  all queries go through `db.run()` so nothing can hit the wrong company's graph.
- **`cli_util.py`** holds the CLI helpers shared by the three CLIs. **`testing.py`** holds the
  shared pytest graph fixtures (loaded with `-p brain.testing`).

## Named Cypher queries

Python never holds Cypher strings. Every query lives in `apps/brain/queries/<folder>/<name>.cypher`
with a leading `//` header (purpose / params / returns) and is fetched by name via
`queries.get("load/person")`. A file may hold several statements separated by `;` (FalkorDB runs one
statement per `GRAPH.QUERY`), which the schema files use. Folders: `schema/` (range, full-text,
vector indexes, applied in order by `schema.py`, "already indexed" errors are skipped), `load/`
(loader writes), `tools/` (agent-facing read queries), `graph/` (the Graph page's whole-graph read,
used by `brain/graph_view.py`), `chat/` (the agents' chat history in agent_<slug>, run by
`agents.checkpoint.run`), `keeper/` (the Keeper's reads and writes on brain_<slug>, run by
`brain/keeper.py`), `ledger/` (the Keeper's ledger in keeper_<slug>, run by
`agents.keeper.store`).

The synthetic company (`apps/brain/examples/synthetic_company`, source type `canonical_jsonl`)
is a small offline dataset for demos and tests; its JSONL is generated by `generate.py`.

## Agents (`apps/agents/agents`)

`agents ask` / `agents chat` run the agent graph (`agents/graph.py`): a `router` hands each turn to
the brain loop; `builder` -> `critic` are unused placeholders (the router never takes them; the
Keeper is the one writer of knowledge). The brain loop (`agents/loop.py`): `call_claude` streams one Messages API call
(anthropic SDK via `llm.client()`; `llm.fallback_params` adds server-side `fallbacks: "default"`
for Sonnet/Opus, Haiku has none) and `run_tools` runs the
requested graph tools (`agents/toolset.py` adapts `brain.tools`; never LLM-written Cypher). Rules:
- State is append-only and in Anthropic block format; assistant content is replayed exactly as
  returned (thinking blocks included), because the API rejects edited history. Never trim it.
- All tool results of one turn go back in one user message; failures are `is_error` results.
- The answer comes through the `submit_answer` tool (forced `tool_choice` is a 400 on current
  models). It may cite only uids seen in tool results; anything else is sent back as an error.
- Keep `agents/system_prompt.md` and the tool list static (no dates, sorted tools) so the prompt
  prefix stays cacheable. Threads are checkpointed in graph `agent_<slug>` (`checkpoint.py`).
- MCP servers (`agents/mcp.py`): a company's `mcp_servers:` (name, https url, optional
  `token_env` naming the env var with its bearer token, optional `allowed_tools`) go on every
  call as `mcp_servers` + one `mcp_toolset` each (after the graph tools, sorted by name), with
  beta `mcp-client-2026-09-15`, which records each server's tool list in a replayed
  `mcp_tool_listing` block. Anthropic runs the MCP calls inside the Claude call; their blocks
  replay with the assistant content (`replayable` keeps paired calls, drops unpaired ones). A
  successful call is citable as `mcp:<server>/<tool>` (label `MCP`); never on `path`. A missing
  token fails the question with a sentence; an unreachable server fails the Claude call.
- `ask.ask_events` streams a run for the Ask page (`ask()` is its last item): each tool call is
  timed and recorded in the append-only `trace` channel with the subgraph it touched
  (`agents/walk.py` turns any tool's rows into nodes + relationships; links the rows only imply
  are `inferred`). A stop is honoured only between saved steps, so the thread stays valid.
- Tests use a scripted fake client (`apps/agents/tests/test_agent.py`); nothing in `make test` calls the API.
  `agents/offline.py` is the same idea for `agents chat --offline`.
- Online traces (`agents/traces.py`): every turn asked from the CLI (`_run_ask`, real Claude only)
  or the Ask API (its worker, before the `answer` event, which then carries `trace_id`) appends
  one `Trace` to `data/traces/<slug>.jsonl`: tools, failed tools, rejected submits, nudges, stop
  (`error` when the run raised), model, tokens (input + cache read + cache write + output),
  latency, sources, the answer and its cited uids. `ask`, `ask_traced` and evals never record.
  A thumbs (`POST .../traces/{id}/feedback`) is an appended `feedback` line; reading folds the
  latest onto its turn. `GET .../traces/summary?days=` (`agents traces`) gives the rates (over all
  turns; zero-source over answered turns) and nearest-rank p50/p95. `ask.run_events` is
  `ask_events` with the raw `Answer` last, for callers that need its tokens and nudges.
- Chat history (`agents/history.py`): every Ask API and CLI turn is also written, as it runs,
  into agent_<slug> beside the checkpoints: `Thread -[:HAS_TURN]-> Turn -[:HAS_CALL]-> LLMCall
  -[:REQUESTED]-> ToolCall -[:TOUCHED]-> Ref` (+ `Turn -[:CITED]-> Ref`; a Ref stands for a
  brain_<slug> uid, since graphs cannot link to each other). A `Recorder` turns the run's events
  into named writes (`apps/brain/queries/chat/`, run by `checkpoint.run`); each Claude response
  is an `llm` event (`loop.llm_event`: text, thinking, tokens, its calls; ToolCall.kind is
  graph, submit, mcp or server). Writes are
  best effort and never stop an answer. One shared chat list per company (no users). Routes in
  `backend/api/threads.py`: list, reopen, delete (with the checkpoints), `refs/{uid}/threads`.
  `agents/backfill.py` (`agents chats-backfill`) replays old checkpoints through the same
  Recorder, by default only threads with a trace line. Tests use `MemoryChatStore`;
  `apps/agents/tests/test_history_graph.py` runs the Cypher (needs `make up`).

- Agent activity (`agents/activity.py`): the Systems page's runs, one `ActivityRun` per run with
  `ActivityStep`s (actor, tool, input, the brain uids each step touched). Every Ask turn in the
  chat history is a run (`runs_from_thread`), and so is every Keeper review (`runs_from_reviews`:
  its pm, qa and keeper steps from the ledger; a review the server lost shows `stopped`).
  `GET .../activity` (`backend/api/activity.py`) merges both, newest first.

### Evals (`apps/agents/agents/evals`)

`make eval` asks the real agent each question in `evals/cases/<slug>.yaml` (run as `python -m agents.evals`) against brain_<slug>
and grades it with deterministic checks (`graders.py`): uids cited (`cite_any/all/none`), graph
tools that ran, answer text (substrings or a regex) and a step budget. Expected uids are literals
or gold refs (`{tool, params, field, top}`) read from the graph when the run starts, so cases
follow the data. Each case runs `REPEAT` times and reports a pass rate; turns of one case share a
thread. Results: `data/evals/<slug>/<time>-<model>-<effort>.jsonl`; `BASELINE=` diffs pass rates
against an earlier file. It calls the API, so it is not part of `make test`;
`apps/agents/tests/test_evals.py` checks the case files and the harness with the scripted client.
`evals/drafts.py` (`make eval-drafts`) turns thumbs-down traces into cases `fb-<trace id>`: the
earlier turns of the thread, then the bad one expecting only an answer, with the bad answer in
comments. They are tagged `draft`, which a plain run skips (`CASE=draft` runs them); write the
real `expect` and drop the tag.

### The Keeper (`agents/keeper`, `roles/keeper.py`, `brain/keeper.py`)

Reviews what the brain could not answer and updates it (spec: docs/agents.md "The Keeper"; design:
`docs/superpowers/specs/2026-10-16-keeper-design.md`). The demo's agents are `brain`, `keeper`,
`pm` and `qa`. Pieces:
- Ledger graph `keeper_<slug>` (survives rebuilds; `make reset` deletes it): Gap, Consult, Claim,
  FollowUp, LogEntry, Review, ReviewStep (`keeper/model.py`), through the `WorkStore` protocol
  (`keeper/store.py`: `KeeperStore` runs `queries/ledger/*`, `MemoryKeeperStore` for tests).
  Records point at brain uids by string. Every status move is guarded in its Cypher.
- Gaps: a failed Ask turn (no answer or zero sources) or a thumbs-down (`keeper/gaps.py`, written
  after the answer or rating is sent, best effort); noticing `stale_owner` and
  `unowned_hot_system` (`keeper/notice.py`, cap `KEEPER_NOTICE_CAP`; a subject whose latest gap
  was dismissed or needs a person is not raised again).
- Review run (`keeper/review.py`): one per company; re-project, notice, pick the budget's gaps,
  pm and qa `consult` jobs, the keeper `decide` job, pm `follow_up`. Each job's graph-tool calls
  and its submit are written as `ReviewStep`s as they run (best effort), so the review appears
  step by step on `/activity`. Releases gaps it did not
  decide; stops with `brain_unavailable` when brain_<slug> is gone. No API key: `skip_review`
  (re-project + notice only, recorded `skipped`); `--offline` plays the policies.
- Fixed rules (`keeper/rules.py`, `keeper/decide.py`), never the model: evidence uids must exist;
  sources win (`conflicts_with_source`, never projected, pm follow-up); critical =
  `replaces_claim`, `high_impact_system` (top quarter by co-change) or `no_source_evidence`, and
  waits for a lead (`approve`/`reject`, guarded: a second decision raises `ClaimNotPending`, 409).
- Projection (`keeper/project.py`, `brain/keeper.py`): accepted claims become `Claim` nodes in
  brain_<slug> with `ABOUT`/`EVIDENCE` edges, after every accept and build; retired claims keep
  their node with a `valid_to`. Ask reads them through `keeper_notes` and `get_entity`.
- Backend: `keeper_runs.py` (one review per company in a thread; after every finished build,
  Review now, budget 0 after an approval; `recover` marks a review a restart cut off `stopped`)
  and `api/keeper.py` (`/api/companies/{slug}/keeper/...`: gaps, claims, log, followups,
  approve/reject, review, review/stop, review/events SSE). No Keeper page: reviews show on the
  Systems page's activity trail (`GET .../activity`), its controls in that page's rail.
- Frontend: Review now in the Systems page's bar; in its rail the claims waiting for a lead
  (`ClaimApproval`: typed name, optional why) and the log (`KeeperLog`), read again when a Keeper
  run starts, steps or ends. Words for reasons, log actions, errors in `src/lib/keeper.ts`; Ask
  marks a cited `Claim` source "Keeper" (`WalkAnswer`).

### Agent roles (`agents/roles`, `agents/work`, `agents/sim`)

The simulated company in [docs/agents.md](docs/agents.md) (the original spec, no longer the
product story; its "Implementation status" says what is built). Agents never message each
other: each reads its queue, makes one decision and writes it; the next agent finds it through
its own queue. Pieces:
- `agents/work/`: the records (`model.py`), every legal task move in one table (`moves.py`: the guard
  each `queries/work/*.cypher` must match), one pydantic model per `submit_*` tool
  (`submits.py`: the write query's params), work-layer read tools (`tools.py`) and the
  `WorkStore` protocol (`store.py`: `read`/`write` by query name, like `db.run`).
  `memory_store.py` is the offline/test double that enforces the same guards; the FalkorDB store
  is phase 2.
- `agents/acl.py`: which database user may read/write which graph (`brain_`, `sim_`, `mem_<slug>_<role>`,
  `agent_`, `keeper_`), and which role each writer user acts as. The store refuses what it does not allow.
- `agents/roles/`: one `ROLE` per module (user, sorted read tools, jobs; prompt in
  `agents/prompts/<role>.md` after `_shared.md`). A job = queue read + optional atomic claim +
  one submit tool + `apply` (named writes).
- `agents/runner.py`: runs a job through the brain loop (`loop.py`, parameterised by prompt,
  submit tool and grounding check), then writes and logs one Episode. Read-only roles log to
  their own memory graph.
- `agents/policies/`: a deterministic policy per job; `ScriptedClient` plays it through the real
  loop, so offline runs hit the same checks as Claude. Tests: `apps/agents/tests/test_work_store.py`,
  `test_agent_roles.py` (fake brain in `agents/testing.py`).
- `agents/sim/`: the orchestrator's tick loop (`STEPS` order) and the scenarios.
Rules: roles cite only uids from this run's tool results; a write that matches nothing changed
nothing; role read tools not yet backed by a query are pinned in `test_tools_still_missing_are_pinned`.

## Backend (`apps/backend/backend`)

HTTP for the frontend, `backend.api:app` (FastAPI, `make api`): its only way in. Routes sit under
`/api/companies/{slug}/...` (overview, builds, tools, ask, graph, threads, activity, keeper); the
slug is resolved only by `deps.company_slug`, which 404s unless `companies/<slug>.yaml` exists.
Behind it:
- `registry.py`: `companies/*.yaml` is the registry; a bad file is reported, not fatal; edits
  round-trip so hand-written comments survive; writes are atomic.
- `config_diff.py` says if a saved change needs a graph rebuild or a new download.
- `jobs.py`: one build per company, at most two at once, progress as SSE events, last build kept
  in `data/jobs/<slug>.json`; a build cut off by a restart is marked `stopped`.
- `/api/onboard/github` adds a company from one public GitHub repo (the rail's + dialog):
  `onboard.py` derives name, slug and window; the create re-checks visibility (private repos are
  refused) and writes and starts under the start lock.
- `api/ask.py`: POST `.../ask` answers one question as SSE (`start`, `step` / `step_done` per tool
  call, `answer` or `error`) from a worker thread; one run per thread_id; closing the stream
  stops the run at its next step.
- `keeper_runs.py` + `api/keeper.py`: Keeper reviews and approvals (see "The Keeper" above).
- CLI `backend reset` (`make reset`) deletes a company's graphs (brain_, agent_, keeper_), build
  history and Ask traces.

## Package rules

- **Dependency rule:** backend → agents → brain, never the reverse; enforced by
  `apps/brain/tests/test_package_boundaries.py`. Agents reach the graph only through
  `brain.tools`; only `brain/db.py` opens FalkorDB connections.
- `brain.testing`, `agents.testing` and `backend.testing` are pytest helpers (graph fixtures,
  fake clients) shipped inside the packages; production code never imports them.

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
