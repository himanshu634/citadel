# Every Cypher query

All under [`apps/brain/queries/`](../apps/brain/queries/). Each file starts with a header:
purpose, parameters, returns, example.

## Tools (read side: CLI, agents, UI)

| File | Purpose |
|---|---|
| `tools/experts_for_system.cypher` | Who knows a system: people ranked by recency-weighted commits and reviews in it, bots excluded, declared owners alongside |
| `tools/owners_vs_experts.cypher` | Systems whose declared owners (CODEOWNERS) are not the top contributors |
| `tools/work_history.cypher` | Recent PRs/issues that changed or mention a system, with authors, reviewers and closed issues |
| `tools/impact_of.cypher` | Systems changed in the same commits as a system (co-change coupling), with their people and owners |
| `tools/path_between.cypher` | Shortest relationship paths between two nodes, either direction (`algo.SPpaths`) |
| `tools/related_work_items.cypher` | Full-text search over PRs/issues/threads, expanded to authors, systems and closing links |
| `tools/related_documents.cypher` | Full-text search over docs/ADRs, with the systems and work items they mention |
| `tools/semantic_search.cypher` | Vector search over chunk embeddings (`Chunk` HNSW index): the best chunk per work item or document, bot text left out |
| `tools/person_profile.cypher` | One person's teams, systems, recent PRs, reviews and declared ownership |
| `tools/open_work_for.cypher` | A person's open tickets |
| `tools/blocked_on.cypher` | What a person's tickets are waiting on |
| `tools/waiting_on.cypher` | Other people's tickets blocked by this person |
| `tools/get_entity.cypher` | Open any node by uid: fields, text and direct neighbours (a retired Keeper claim is never listed) |
| `tools/keeper_notes.cypher` | The Keeper's accepted, current claims about a node, each with its evidence |
| `tools/list_systems.cypher` | All systems with change counts, people and owners |
| `tools/recent_work_items.cypher` | Most recent PRs, issues and threads, newest first (dashboard overview) |
| `tools/collaborators.cypher` | Pairs of people ranked by PRs one reviewed of the other's, with shared issue threads, bots excluded |
| `tools/issues_by_system.cypher` | Issues and tickets per system (text names it, or closed by a PR that changed it), open/closed, ranked |
| `tools/people_activity.cypher` | People with how many PRs they authored and reviewed, bots excluded (dashboard overview) |
| `tools/central_nodes.cypher` | The most central systems, work items or documents: PageRank over the whole graph (`algo.pageRank`), bot work left out |
| `tools/bottlenecks.cypher` | Work items on the most dependency chains between other work: betweenness over `BLOCKS`/`CLOSES`/`MENTIONS` (`algo.betweenness`, 8 seeded samples summed) |
| `tools/graph_stats.cypher` | Node and relationship counts per type |

One tool has no file: `run_cypher` ([`brain/cypher.py`](../apps/brain/brain/cypher.py)) runs one
read query Ask writes when no tool above fits. FalkorDB runs it as `GRAPH.RO_QUERY`, so writes
are refused; it has a 5 s timeout, must carry a `LIMIT`, and may not use `LOAD CSV`. Only Ask (and the CLI)
can call it: the HTTP API does not serve it. Ask learns the schema from
[`agents/skills/cypher/SKILL.md`](../apps/agents/agents/skills/cypher/SKILL.md), which is part of its
system prompt.

## Schema

| File | Purpose |
|---|---|
| `schema/range_indexes.cypher` | Range indexes on every label's `uid`, plus `Person.login`, `WorkItem.number`, `System.name` |
| `schema/node_label.cypher` | Gives every node the `Node` label beside its kind, so a lookup by uid alone is an index scan |
| `schema/fulltext_indexes.cypher` | Full-text indexes on `WorkItem` and `Document` title and body |
| `schema/vector_index.cypher` | HNSW cosine vector index on `Chunk.embedding` (dimension from `EMBEDDING_DIM`) |
| `schema/list_indexes.cypher` | List indexes; a vector index whose dimension is not `EMBEDDING_DIM` fails the schema step |

## Load (write side, run by ingest)

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

## The Keeper

| Folder | Runs on | Purpose |
|---|---|---|
| `keeper/` | `brain_<slug>` | What the Keeper checks a claim against (`evidence`, `source_facts`, `high_impact_systems`), the noticing queries (`notice_stale_owner`, `notice_unowned_hot_system`), and writing claims into the brain (`project_claim`, `retire_claim`) |
| `ledger/` | `keeper_<slug>` | The ledger: gaps (`open_gap` dedupes), consults, claims, follow-ups, the append-only log and review runs. Every status move is guarded on the current status, so of two racing approvals one wins |

