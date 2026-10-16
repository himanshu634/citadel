# Graph model

Each company is its own FalkorDB graph, `brain_<slug>` (agent conversation checkpoints live
apart, in `agent_<slug>`). Nothing is shared between company graphs, so one company's query can
never see another's data. FalkorDB is the only store: the product reads nothing else at runtime.

```mermaid
graph LR
  Person -- AUTHORED --> Change
  Person -- AUTHORED --> WorkItem
  Person -- AUTHORED --> Document
  Person -- ASSIGNED_TO --> WorkItem
  Person -- "REVIEWED {state}" --> WorkItem
  Person -- "COMMENTED_ON {count, last_at}" --> WorkItem
  Person -- MEMBER_OF --> Team
  Team -- "OWNS {pattern}" --> System
  Person -- "OWNS {pattern}" --> System
  Change -- "TOUCHES {files}" --> System
  Change -- PART_OF --> WorkItem
  WorkItem -- CLOSES --> WorkItem
  WorkItem -- BLOCKS --> WorkItem
  WorkItem -- MENTIONS --> WorkItem
  WorkItem -- MENTIONS --> System
  Document -- MENTIONS --> WorkItem
  Document -- MENTIONS --> System
  Chunk -- FROM --> WorkItem
  Decision -. "MADE_IN (later)" .-> WorkItem
  Decision -. "AFFECTS (later)" .-> System
  Decision -. "SUPERSEDES / CONTRADICTS (later)" .-> Decision
  Episode -. "READ / WROTE (later)" .-> Person
```

## Nodes

Every node has `uid` (stable; re-ingesting the same thing updates it in place), `company`,
`source` (`github`, `canonical_jsonl`, `local_docs`, `derived` ...) and, where one exists, `url`
(the citation a human can open). Timestamps are ISO strings (`created_at`, `date`) plus epoch
seconds (`created_ts`, `ts`) for recency maths, because FalkorDB temporal values have no epoch
accessor.

| Label | Key properties | Comes from |
|---|---|---|
| `Person` | `login`, `display_name`, `is_bot` | authors, reviewers, commenters, CODEOWNERS; uid `person:<login>` (lower-case) |
| `Team` | `name` | CODEOWNERS `@org/team`, JSONL; uid `team:<name>` |
| `System` | `name`, `path_rule` | file paths mapped by the company's `systems.rules`; uid `system:<name>` |
| `Change` | `sha`, `date`, `ts`, `kind` (feat/fix/perf/ci/build/docs/refactor/other), `subject` | commits |
| `WorkItem` | `kind` (pull_request/issue/ticket/thread), `number`, `title`, `body`, `state`, `created_at`, `closed_at`, `merged_at`, `labels`, `container`; tickets also `key`, `status_category` (backlog/todo/in_progress/done/canceled), `priority` (urgent/high/medium/low), `priority_rank` (1-4, 5 = none; null for PRs and issues), `due_date`, `due_ts` | PRs, issues, tickets, chat threads |
| `Document` | `path`, `title`, `body`, `updated_at` | repo markdown, published docs folders |
| `Chunk` | `kind`, `text`, `author_uid`, `ts`, `embedding` (vector, filled later) | comment text today; document/PR chunks for semantic search later |
| `Decision` | `summary`, `rationale`, `valid_from`, `valid_to` | defined now, written later by the Builder agent |
| `Episode` | `agent`, `run_at`, `input`, `summary` | agent memory, written later |
| `SyncState` | `adapter`, `key`, `cursor`, `window_since`, `last_run`, `records` | ingestion bookkeeping, one per configured source |

People and systems get source-free uids, so the same login seen in GitHub and in a Slack export
is one node. No email addresses are stored anywhere: people are identified by login, and
normalize scrubs addresses out of every text field.

## Relationships

| Relationship | Meaning |
|---|---|
| `(Person)-[:AUTHORED]->(Change \| WorkItem \| Document)` | wrote it |
| `(Person)-[:REVIEWED {state, submitted_at, ts}]->(WorkItem)` | latest review per person and PR |
| `(Person)-[:COMMENTED_ON {count, last_at}]->(WorkItem)` | count recomputed from comment chunks, so it stays right on incremental ingests |
| `(Person)-[:MEMBER_OF]->(Team)` | team membership (when the source exposes it) |
| `(Team \| Person)-[:OWNS {pattern}]->(System)` | declared ownership (CODEOWNERS), patterns matched against the real file tree |
| `(Person)-[:ASSIGNED_TO]->(WorkItem)` | current assignees of a ticket. Replaced on every load: the item's old edges are deleted, then one is written per assignee, so reassigning moves it and an empty list unassigns. A source that does not track assignees (`None`) leaves the edges alone. `source` is the item's source |
| `(WorkItem)-[:BLOCKS {source, origin, uid}]->(WorkItem)` | ticket dependency. `origin` is the adapter key; after a load, edges with that origin whose `uid` the load did not write are deleted, so a removed dependency disappears. Other origins are never touched |
| `(Change)-[:TOUCHES {files}]->(System)` | which code areas a commit changed, and the files in each |
| `(Change)-[:PART_OF]->(WorkItem)` | commit belongs to a PR (PR commit list, merge commit, or `(#123)` in the subject) |
| `(WorkItem)-[:CLOSES]->(WorkItem)` | PR closes issue |
| `(WorkItem \| Document)-[:MENTIONS]->(WorkItem \| System)` | `#123` / PR URLs, and repo paths such as `src/index/`. A ticket can name a work item by its `url` (for example a GitHub PR): the loader matches it to the work item with that `url` |
| `(Chunk)-[:FROM]->(WorkItem)` | where a piece of text came from |
| `(Decision)-[:MADE_IN \| AFFECTS \| SUPERSEDES \| CONTRADICTS]` | later (Builder / Critic agents) |

## Expertise is derived, not stored

"Who knows this system?" is computed at query time from
`(Person)-[:AUTHORED]->(Change)-[:TOUCHES]->(System)` plus reviews of PRs whose commits touch the
system, each event weighted by recency (`experts_for_system`). No "expert" edge is ever written,
so the answer is current as soon as new commits are ingested, and the evidence (the commits and
PRs) is always one hop away for citation.

## Indexes (`queries/schema/`)

- Range indexes on every label's `uid`, plus `Person.login`, `WorkItem.number`, `WorkItem.key`, `WorkItem.url`, `System.name`.
- Full-text (RediSearch) on `WorkItem(title, body)` and `Document(title, body)`.
- Vector (HNSW, cosine) on `Chunk.embedding`, dimension `EMBEDDING_DIM`.

`make schema SLUG=<slug>` applies them; re-running is safe.

## Ingest window

A company config's `window.since` bounds the graph. Commits before it are not loaded. A PR,
issue or thread is loaded when it was created, closed or merged in the window, or got a comment
or review in it. A bare `updated_at` bump (a bulk relabel or a bot sweep) does not count.
An open ticket (its `status_category` is not `done` or `canceled`) is always loaded, whatever its
dates, so the graph keeps the current backlog.
