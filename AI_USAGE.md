# AI usage

Citadel was built with Claude Code as the coding assistant. A human set every goal and rule and
picked every design direction; the assistant wrote almost all of the code, tests, queries and
docs. This file says what it built, what the humans decided, and how the result was checked.

## How we worked

- **One loop for every part.** The human sets the goal and the rules. The assistant reads the
  code and drafts either a plan or, for anything on screen, three or four mockup directions on a
  design canvas. The human picks one (often with changes). The assistant builds it on its own
  branch in a git worktree, with tests, and opens a PR. The human reviews and merges.
- **Many sessions at once.** Several Claude Code sessions ran in parallel, each in its own
  worktree and branch, to keep their edits apart.
- **Defaults are named.** When a plan or a design round left a question the human skipped, the
  assistant took a default and wrote it in the PR under "Decisions" or "Defaults taken". The
  embedding model and the graph renderer are two such choices.
- **Authoring is not the product.** The agents inside Citadel (`brain`, `keeper`, `pm`, `qa`)
  also run on Claude, through the Anthropic API. That is how the product works, not how it was
  written.

## What the assistant built, by part

Every part below was written by the assistant from a human brief. "Early" means a commit on
`main` from before the repo had a remote, so it has no PR.

| Part | What the assistant did | Key PRs |
|---|---|---|
| Workspace and tooling | uv workspace, Docker Compose, config models, the Makefile, three CLIs; later split into `apps/brain`, `apps/agents`, `apps/backend` with a boundary test | early (905c580, 0a0dd24), #10, #19, #21 |
| FalkorDB layer and schema | `apps/brain/brain/db.py`, range, full-text and vector indexes, TLS for FalkorDB Cloud | early (905c580, e6731ff) |
| Canonical model, normalize, loader | `canonical.py`, company rules, email scrubbing, idempotent `MERGE` loads, the synthetic company | early (5a1d43b), #3 |
| Adapters | GitHub (GraphQL runs, partial clone, CODEOWNERS), Linear, local docs, canonical JSONL | #4, #18 |
| Chunks and embeddings | chunking, fastembed and Gemini providers, incremental embed stage, `semantic_search` | #34, #35, #37, #42 |
| Named Cypher tools | every `apps/brain/queries/tools/*.cypher`, typed params and rows, the `brain query` CLI | #5, #52 |
| Ask agent | the brain loop, `submit_answer` and the grounding check, model choice, step limits | #2, #9, #41, #43 |
| Ask page | the graph walk (direction D), then lanes and a step ledger (J + L), the model picker (P), GitHub links | #14, #24, #25, #39 |
| MCP client | a company's MCP servers on every Ask call, cited as `mcp:<server>/<tool>` | #23 |
| Chat history and traces | `Thread → Turn → LLMCall → ToolCall` in `agent_<slug>`, trace lines, thumbs, eval drafts | #22, #16 |
| Offline evals | `make eval`, deterministic graders, case files for `synthetic` and `falkordb` | #15, #51 |
| The Keeper | gaps, noticing, review runs, fixed rules, projection, approvals, the interview | #36, #38, #46, #47, #48 |
| `pm`, `qa`, `keeper` roles | role jobs, prompts, the runner and offline policies | #13 (trimmed by #50) |
| Backend | FastAPI routes, build jobs and SSE, the company registry, one-repo onboarding | #7, #11, #19 |
| Frontend frame | the design system (theme H), the company rail (A), sidebar motion, dev proxy | #1, #7, #26, #40 |
| App pages | Graph (territories, D), Settings (B), Systems (A), Sources (A), Linear in the form | #17, #27, #28, #29, #30, #31 |
| Docs and diagrams | README, `docs/`, the Excalidraw diagrams in `docs/architecture/`, DEVELOPMENT.md | #6, #20, #32, #33, #44, #49 |

Removed or dropped: the agent simulation (nine roles and a sim loop, #13) was removed in #50.
Google Cloud / Vertex AI settings were dropped in #8. An MCP server that exposes the graph to
outside agents was considered and dropped before any code was written.

## What we designed

These are human decisions. The assistant implemented them; it did not choose them.

- **One graph per company** (`brain_<slug>`). Why: no query can mix two companies' data, and a
  company is deleted by deleting its graphs.
- **Named tools only, no LLM-written Cypher.** Why: every query that reaches the graph is one we
  wrote and reviewed, so an answer is never the product of an invented query.
- **The grounding check.** An answer may cite only uids seen in this run's tool results. Why: a
  citation must point at something the agent actually read.
- **Sources win.** A Keeper claim that contradicts the sources is never written into the brain;
  `pm` opens a follow-up to fix the source. Why: the Keeper fills what the sources do not say, it
  does not overrule them.
- **The critical rule and lead approval.** A claim that replaces another, touches a high-impact
  system or rests on no source waits for a lead. Why: the risky writes need a person; the rest
  should not.
- **The ledger is the only channel between agents.** Why: no agent calls another, so every
  exchange is stored and can be audited.
- **The Keeper is the single writer of knowledge.** Ask may only file a person's reply as a
  pending claim. Why: one place to check, log and undo every change to what the brain knows.
- **Public, synthetic or own data only, and no email addresses.** Why: nothing private or personal
  reaches a graph by accident.
- **The design directions.** The human picked each one from a mockup canvas: theme H ("Wide
  type, calm body"), the company rail A, repo-first onboarding D (public repos only), the Ask
  walk D and then lanes J + L, the model picker P, Graph territories D, Settings B, Systems A and
  Sources A.

## What we verified, and how

Run on 2026-10-17 against FalkorDB in local Docker:

- **`make test`: 869 passed, 0 skipped.** This includes the graph tests on throwaway graphs, the
  chat-history and ledger Cypher on a real FalkorDB, and `test_agent_live.py`, which asks Claude
  one real question on `brain_synthetic`.
- **`make fe-test`: 481 tests passed in 27 files** (vitest). `make fe-check` (svelte-check) and
  `make lint` (ruff) are clean.
- **Live GitHub ingest.** `brain_falkordb` is built from the public FalkorDB/FalkorDB repo: 18,424
  nodes, 7,716 embedded chunks, and 3,728 records loaded in its last sync.
- **Live agent runs.** Ask was used on both companies: 19 traced turns and 4 thumbs in the local
  trace files. A live Keeper review ran after the simulation was removed, and `brain_falkordb`
  holds one Keeper `Claim` node.
- **Agent evals.** Real Claude runs graded by deterministic checks; results are in
  [Evals](docs/evals.md).
- **In the browser.** Pages were checked against a running API during their PRs. Onboarding was
  run end to end on a public repo, a Sonnet question then a Haiku follow-up ran in one thread, and
  a name-only Settings save was run live.

## What is not verified

- **MCP connector.** Never run against a real MCP server; tested only with scripted clients. MCP
  calls are not in the trace lines.
- **Linear, live.** The adapter is tested on a hand-written cache. Seeding a real workspace
  (`make linear-seed`) and syncing it is left to the user; `brain_synthetic_linear` was never
  built.
- **Database users.** `apps/agents/agents/acl.py` renders `ACL SETUSER` lines, but nothing
  applies them. All agents share one FalkorDB connection; the permission table is checked in code
  only.
- **FalkorDB Cloud.** The TLS setting exists; this record shows no run against Cloud.
- **Models.** Only Haiku 5.5 and Sonnet 5.5 were run live from the picker; Opus 5.5 and Fable 5.1
  were not.
- **Edge states.** Onboarding without a GitHub token or past the rate limit was checked only in
  unit tests and the component gallery. A Settings save that needs a rebuild was not run live.
