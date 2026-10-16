# Company Brain

**A living memory of how your company builds software, one that agents can query and that
repairs itself.**

Entry for *Graph Hacks: Context for AI Agents* (FalkorDB × WeMakeDevs, Oct 15–18 2026).
Tracks: **Company Brain** and **Agent Memory & Coordination**.

## The problem

Every team keeps asking the same questions: *who knows this system? why was this decided? what
breaks if we change it?* The answers already exist, scattered across commits, pull requests,
reviews, tickets and docs. Nobody can hold all of it in their head, and AI assistants without
that context guess.

Company Brain puts it all in **one graph per company** and answers from it, with the sources and
the graph path behind every answer. When the graph does not know something, it does not guess:
the **Brain Curator** finds out, checks the answer, and writes it back. Each question it cannot
answer makes the brain better for the next person.

## What we are building

| Part | What it does | Status |
|---|---|---|
| **The Brain** | One FalkorDB graph per company (`brain_<slug>`), built from GitHub, Linear, docs and chat exports: people, teams, systems, changes, work items, documents | Built |
| **Named graph tools** | 16 read queries, each a reviewed `.cypher` file with typed params. Agents pick a tool and fill its params; no LLM ever writes Cypher | Built |
| **Ask** | A Claude agent that answers from the tools and may cite only the nodes it has seen. Every turn is traced (no-answer, zero-source, thumbs) | Built |
| **Role agents** | PM, Developer, QA, DevOps, Reviewer, Risk, Builder and Critic, working a shared task board inside the graph. They never message each other: the graph is the only channel ([spec](docs/agents.md)) | Built offline, FalkorDB work store next |
| **Brain Curator** | Turns unanswered or stale questions into gaps, consults the role agents, verifies their claims, gets a human yes, and writes the new knowledge into the brain | Planned |
| **MCP server** | The same named tools for any outside agent (Claude, an IDE, a Slack bot), read-only, plus one gated `propose_claim` write | Planned |
| **Designer agent** | A design-review voice for the curator to consult | Planned |

## How it works

![Company Brain overview: people, the brain, the curator and the role agents](docs/architecture/overview.svg)

- **People ask, the brain answers.** A CEO or tech lead asks in the app; any other AI agent asks
  over MCP. Both go through the same named tools and get an answer with sources and a graph path.
- **The curator takes over when the brain cannot answer.** The answer may be missing, have no
  source, get a thumbs down, or contradict a newer fact. The curator works out who should know,
  posts consult tasks, and collects the replies.
- **Agents talk through the graph.** Each role agent reads its queue on the shared board, answers
  with claims that cite real nodes, and writes them back. No agent calls another directly, so
  every exchange is stored, can be audited and can be replayed.
- **Only verified knowledge reaches the brain.** The curator checks the evidence and asks the lead
  to confirm. It then writes the fact as its own dated node, linked to its evidence.

## Inside the brain

![Ingest pipeline, FalkorDB graphs and the read side with the grounding check](docs/architecture/brain-internals.svg)

- **Ingest is a one-way pipeline.** Adapters fetch into a raw cache, records become canonical
  (stable uids, no emails), company rules from `companies/<slug>.yaml` are applied, and the loader
  `MERGE`s everything on uid. Loads are idempotent, and a re-ingest makes no API calls.
- **FalkorDB is the only store.** Each company is an isolated graph `brain_<slug>`, with range,
  full-text and vector indexes. Chat state is checkpointed in `agent_<slug>`.
- **The read side is deterministic.** Claude chooses which named tool to call. The query is always
  one we wrote and reviewed. A grounding check rejects any answer that cites a node the agent did
  not see.
- **Expertise is derived, not stored.** It is computed from Person → Change → System, weighted by
  recency, at query time, so it is current the moment new commits land.

## The self-healing loop

![The self-healing loop: gap, curator, consult, verify, approve, write, re-ask](docs/architecture/self-healing-loop.svg)

The plan for the curator, based on how Graphiti, Mem0, Wikidata and others keep a graph honest:

1. **Detect gaps** from live traffic (no answer, zero sources, thumbs down) and from a sweeper
   that looks for stale owners, expired facts and conflicting decisions.
2. **Consult the right people.** `experts_for_system` names who knows the area, and the matching
   role agents get consult tasks on the board.
3. **Verify before writing.** Every claim must cite uids that really exist. The Critic labels each
   claim as superseding, contradicting or unrelated to what the brain already holds. A lead
   approves the result.
4. **Never delete, invalidate.** New knowledge lives in its own `Claim` / `Decision` nodes, so a
   re-ingest never overwrites it. An outdated fact gets a `valid_to` date and stays for history.
   Rejected claims are kept with the reason.
5. **Prove the fix.** The original question is asked again and becomes an eval case, so the
   brain cannot quietly forget it.

The `.excalidraw` files next to each SVG in [docs/architecture/](docs/architecture/) open at
[excalidraw.com](https://excalidraw.com) (File → Open) for editing; the `.mmd` files are the source.

## Quick start

Full setup, prerequisites and troubleshooting: **[DEVELOPMENT.md](DEVELOPMENT.md)**.

```bash
make setup        # uv sync + .env from .env.example
make up           # FalkorDB on :6379, Browser UI on http://localhost:3000
make synthetic    # offline demo company, no tokens needed
make query SLUG=synthetic TOOL=owners_vs_experts
make dev          # API on :8000 + app on http://localhost:5173
```

With a GitHub token, `make sync` builds `brain_falkordb` from the FalkorDB repo itself. With
`ANTHROPIC_API_KEY` set, `make ask SLUG=synthetic Q="who knows Auth?"` gets an answer from Claude.

## The graph

Full model: **[docs/graph-model.md](docs/graph-model.md)**.

Nodes: `Person`, `Team`, `System`, `Change`, `WorkItem` (PRs, issues, tickets, threads),
`Document`, `Chunk`, `Decision` and `Episode` (written by the agents), `SyncState`.
Relationships: `AUTHORED`, `REVIEWED`, `COMMENTED_ON`, `MEMBER_OF`, `OWNS`, `TOUCHES`,
`PART_OF`, `CLOSES`, `MENTIONS`, `BLOCKS`, `ASSIGNED_TO`, `FROM`.

## Every Cypher query

All under [`apps/backend/queries/`](apps/backend/queries/). Each file starts with a header:
purpose, parameters, returns, example.

### Tools (read side: CLI, agents, UI, MCP)

| File | Purpose |
|---|---|
| `tools/experts_for_system.cypher` | Who knows a system: people ranked by recency-weighted commits and reviews in it, bots excluded, declared owners alongside |
| `tools/owners_vs_experts.cypher` | Systems whose declared owners (CODEOWNERS) are not the top contributors |
| `tools/work_history.cypher` | Recent PRs/issues that changed or mention a system, with authors, reviewers and closed issues |
| `tools/impact_of.cypher` | Systems changed in the same commits as a system (co-change coupling), with their people and owners |
| `tools/path_between.cypher` | Shortest relationship paths between two nodes, either direction (`algo.SPpaths`) |
| `tools/related_work_items.cypher` | Full-text search over PRs/issues/threads, expanded to authors, systems and closing links |
| `tools/related_documents.cypher` | Full-text search over docs/ADRs, with the systems and work items they mention |
| `tools/person_profile.cypher` | One person's teams, systems, recent PRs, reviews and declared ownership |
| `tools/open_work_for.cypher` | A person's open tickets |
| `tools/blocked_on.cypher` | What a person's tickets are waiting on |
| `tools/waiting_on.cypher` | Other people's tickets blocked by this person |
| `tools/get_entity.cypher` | Open any node by uid: fields, text and direct neighbours |
| `tools/list_systems.cypher` | All systems with change counts, people and owners |
| `tools/recent_work_items.cypher` | Most recent PRs, issues and threads, newest first (dashboard overview) |
| `tools/people_activity.cypher` | People with how many PRs they authored and reviewed, bots excluded (dashboard overview) |
| `tools/graph_stats.cypher` | Node and relationship counts per type |

### Schema (`make schema`)

| File | Purpose |
|---|---|
| `schema/range_indexes.cypher` | Range indexes on every label's `uid`, plus `Person.login`, `WorkItem.number`, `System.name` |
| `schema/fulltext_indexes.cypher` | Full-text indexes on `WorkItem` and `Document` title and body |
| `schema/vector_index.cypher` | HNSW cosine vector index on `Chunk.embedding` (dimension from `EMBEDDING_DIM`) |
| `schema/list_indexes.cypher` | List indexes; used to warn when the vector dimension does not match |

### Load (write side: `make ingest`)

| File | Purpose |
|---|---|
| `load/person.cypher`, `load/team.cypher`, `load/system.cypher` | Upsert people, teams, systems (MERGE on uid, then SET) |
| `load/work_item.cypher`, `load/document.cypher`, `load/change.cypher` | Upsert PRs/issues/tickets/threads, documents, commits |
| `load/authored_*.cypher` | `(Person)-[:AUTHORED]->(...)`, one file per target label |
| `load/touches.cypher` | `(Change)-[:TOUCHES {files}]->(System)` |
| `load/reviewed.cypher` | `(Person)-[:REVIEWED {state}]->(WorkItem)`, latest review wins |
| `load/comment_chunk.cypher`, `load/commented_on.cypher` | Comment text as a `Chunk` FROM its work item; `COMMENTED_ON {count, last_at}` |
| `load/owns_team.cypher`, `load/owns_person.cypher` | Declared ownership `OWNS {pattern}` |
| `load/assigned_to.cypher` | Ticket assignee, replaced on every load |
| `load/link_blocks.cypher`, `load/prune_blocks.cypher` | `BLOCKS` between tickets; edges a source no longer reports are pruned |
| `load/link_*.cypher` | `CLOSES`, `PART_OF`, `MEMBER_OF` and `MENTIONS` (one file per allowed label pair, plus by-url) |
| `load/sync_state_*.cypher` | Incremental-ingest cursor per configured source |

Relationship types and labels cannot be Cypher parameters, which is why each allowed
combination has its own small file rather than one query built from strings.

## Adding a company

**[docs/adding-a-company.md](docs/adding-a-company.md)**: (a) a public GitHub repo (copy the
config, edit the path rules, sync), (b) Linear, or Slack/Jira exports via
[canonical JSONL](docs/canonical-format.md), or a new adapter (skeleton in
`apps/backend/brain/adapters/_template.py`), (c) a synthetic demo company. In the app, the **+**
on the company rail adds any public GitHub repo.

## Ground rules

- **Only public, synthetic or own data.** Each config declares `data_permission`. Private
  GitHub repos are refused unless it is `own`. No email addresses are stored anywhere.
- **Company-agnostic.** A new company is a YAML file. A new kind of source is one adapter module
  plus one registry line, with no change to the loader, schema or queries.
- **Every answer is grounded.** Cited uids must come from this run's tool results; anything else
  is sent back to the agent as an error.

## Repository

```
apps/backend/     Python 3.12 (uv): ingestion, schema, named queries, agents, API. CLI: brain
  brain/            adapters/, pipeline, loader, tools, agents/, work/, sim/, api/
  queries/          schema/, load/, tools/, graph/  (every Cypher query)
  evals/            agent evals and thumbs-down drafts
  examples/         synthetic_company/ (offline demo data + generator)
  tests/            pytest; graph tests use a real FalkorDB (make up) and throwaway graphs
apps/frontend/    SvelteKit app and design system
companies/        one YAML per company -> graph brain_<slug>
docs/             graph model, agents spec, architecture diagrams, adding a company
data/             gitignored: raw API caches, build history, traces
```

## AI usage

An AI coding assistant was used to build this project; what it did is listed in
[AI_USAGE.md](AI_USAGE.md).
