# Citadel: Company Brain and its Keeper

**A living memory of how your company builds software that agents can query, and the Keeper: the
agent that repairs it.**

Citadel is our entry for *Graph Hacks: Context for AI Agents* (FalkorDB × WeMakeDevs, Oct 15–18 2026).
Tracks: **Company Brain** and **Agent Memory & Coordination** ([how Citadel covers Track 02](#agent-memory--coordination-track-02)).

## The problem

Every team keeps asking the same questions: *who knows this system? why was this decided? what
breaks if we change it?* The answers are already there, spread across commits, pull requests,
reviews, tickets and docs. Nobody can keep all of it in their head, and an AI assistant without
that context guesses.

Citadel puts it all in **one graph per company** and answers from it, with the sources and the
graph path behind every answer. When the graph does not know something, it does not guess: the
**Keeper** finds out, checks the answer against the sources, and writes it back.

## How it works

![The big picture: sources, the brain, Ask, the Keeper and the Archivist](docs/architecture/overview.svg)

*Sources become one graph per company, Ask answers from that graph, and whatever Ask can't answer
goes to the Keeper, which fills the gap in the brain.*

1. **Sources.** GitHub, Linear, docs and Slack/Jira exports. In the app, paste any public GitHub repo.
2. **Company Brain.** One FalkorDB graph per company: people, teams, systems, changes, PRs,
   issues, tickets, documents.
3. **Ask.** A Claude agent that answers through reviewed, named Cypher tools and may cite only
   nodes it has seen. Every answer comes with its sources and a graph path.
4. **Keeper.** Turns failed questions and thumbs-downs into gaps, works them out with the `pm`
   and `qa` agents, and writes checked claims back into the brain.
5. **Archivist.** When a question needs history older than the ingest window, it fetches it
   from GitHub or Linear on demand and loads it ([spec](docs/agents.md#the-archivist)).

## The Keeper: a brain that heals itself

![The self-healing loop: gap, consult, fixed checks, claim, ask again](docs/architecture/self-healing-loop.svg)

*Every question the brain can't answer makes it better for the next person.*

1. **Gap.** A question with no answer or no source, or a thumbs-down, opens a gap. After each
   build the Keeper also notices gaps by itself: stale owners, and busy systems that nobody owns.
2. **Consult.** The Keeper asks `pm` and `qa`. Each one answers with a draft claim that cites
   real nodes.
3. **Fixed checks, in code, not the model.** The evidence must exist in the brain. **Sources win:**
   a claim the sources contradict is never written, and `pm` opens a follow-up to fix the source.
   A critical claim (it replaces a claim, touches a high-impact system, or has no source behind
   it) waits for a lead on the **Review claims** page.
4. **Claim.** An accepted claim becomes a dated `Claim` node linked to its evidence. A newer claim
   replaces it, and nothing is deleted.
5. **Ask again.** The next answer cites the claim and says it comes from the Keeper.

Every step is logged (who, what, why, who approved) and shows step by step on the Systems page.
Full spec: [docs/agents.md](docs/agents.md#the-keeper).

## Inside the brain

![Ingest pipeline into three FalkorDB graphs, read through named tools by Ask](docs/architecture/brain-internals.svg)

*Data goes one way into the graph. Agents read it back only through tools we wrote.*

- **Ingest is idempotent.** Adapters fetch into a raw cache, records get stable uids (no
  emails), company rules from `companies/<slug>.yaml` apply, and the loader `MERGE`s on uid.
  A re-ingest makes no API calls.
- **Three graphs per company:** `brain_<slug>` (what the company knows), `agent_<slug>` (chat
  memory) and `keeper_<slug>` (the Keeper's ledger, which survives a rebuild).
- **The read side is deterministic.** Claude picks one of 22 named, reviewed Cypher tools. For
  anything they miss, Ask may write one read-only query (`GRAPH.RO_QUERY`, 5 s timeout,
  `LIMIT` required). A grounding check rejects any citation the agent did not see.

**FalkorDB features in use:** `algo.SPpaths` (how two things connect), `algo.pageRank` (central
systems, and what counts as high impact), `algo.betweenness` (bottleneck tickets), variable-length
`BLOCKS` paths, full-text indexes, an HNSW vector index for semantic search, and `GRAPH.RO_QUERY`.
Every query: [docs/queries.md](docs/queries.md). Graph model: [docs/graph-model.md](docs/graph-model.md).

## Agent Memory & Coordination (Track 02)

| Track 02 asks for | In Citadel | Proof (test) |
|---|---|---|
| **Episodic memory** | Every Ask turn as a graph in `agent_<slug>` (`Thread → Turn → LLMCall → ToolCall → Ref`), every Keeper review as `Review` + `ReviewStep`s, and an append-only log | `test_history_graph.py`, `test_keeper_store.py` |
| **Semantic memory** | Accepted claims as `Claim` nodes in the brain, with `ABOUT` and `EVIDENCE` edges, cited by Ask | `test_keeper_decide.py` |
| **Memory that changes** | Claims have `valid_from` / `valid_to`; a new claim supersedes the old one. After each build, a claim the sources now contradict is superseded, and one whose evidence is gone reopens its gap | `test_supersedes_earlier_claim`, `test_stale_on_projection_missing` |
| **Procedural memory** | Named Cypher tools, the Keeper's fixed rules and one prompt per role, all in reviewed files | `test_keeper_rules.py` |
| **Shared state and handoffs** | Agents never message each other. The ledger is the only channel: the Keeper posts a `Consult`, each role answers from its own queue | `test_keeper_review.py`, `test_keeper_jobs.py` |
| **Concurrency** | Every status change is guarded in its Cypher, so of two racing approvals one wins and the other gets HTTP 409 | `test_claim_status_guard`, `test_approve_twice` |
| **Isolation** | One graph per company, opened in one place (`brain/db.py`); a permission table says which agent user may touch which graph | `test_isolation.py`, `test_keeper_acl.py` |

## Evals

`make eval` asks Claude fixed questions on a loaded brain and grades each answer with
deterministic checks: cited uids, tools run, answer text and step count. Each case runs 3 times
(2026-10-17):

| Company | Cases | Haiku 5.5 | Sonnet 5.5 (default) |
|---|---:|---:|---:|
| synthetic (offline demo) | 17 | 47/51 (92%) | 51/51 (100%) |
| falkordb (FalkorDB/FalkorDB repo) | 23 | 65/69 (94%) | 68/69 (99%) |

Tables by tag and case, the misses and how to run them again: [docs/evals.md](docs/evals.md).

## Running it

With Docker (running), [uv](https://docs.astral.sh/uv/), Node.js 22 and pnpm installed:

```bash
git clone https://github.com/himanshu634/citadel.git && cd citadel
make start
```

It checks your tools, `.env`, ports and disk first, then installs, starts FalkorDB, builds the
offline synthetic demo company and serves the app on <http://localhost:5173>. Add
`ANTHROPIC_API_KEY` to `.env` to ask questions; a GitHub token builds a brain from a public repo.
Every command and troubleshooting: [DEVELOPMENT.md](DEVELOPMENT.md). New company:
[docs/adding-a-company.md](docs/adding-a-company.md).

## Ground rules

- **Only public, synthetic or own data.** Private GitHub repos are refused unless the config says
  `data_permission: own`. No email addresses are stored.
- **Company-agnostic.** A new company is one YAML file. A new source is one adapter module.
- **Every answer is grounded.** Cited uids must come from this run's tool results.

## Repository

```
apps/brain/      the engine: adapters, pipeline, loader, named Cypher queries, FalkorDB access
apps/agents/     Claude agents (Ask, Keeper, pm, qa, Archivist), evals, traces
apps/backend/    FastAPI for the app
apps/frontend/   SvelteKit app
companies/       one YAML per company -> graph brain_<slug>
docs/            graph model, agents spec, queries, evals, diagrams
```

Dependencies go one way only: backend → agents → brain. The diagrams are Excalidraw scenes in
[docs/architecture/](docs/architecture/); open a `.excalidraw` file at
[excalidraw.com](https://excalidraw.com) to edit it.

## AI usage

I used Claude Code to write the code; the design and the decisions are mine.
[AI_USAGE.md](AI_USAGE.md) says how I used it.
