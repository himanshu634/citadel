---
name: graph-cypher
description: How to write a read-only Cypher query for the `run_cypher` tool against one company's FalkorDB graph (brain_<slug>): its labels, properties, relationships and the rules that keep a query fast and its rows citable. Use when no named graph tool fits the question.
---

# Writing a query for `run_cypher`

`run_cypher` runs one openCypher statement that you write on this company's graph in FalkorDB.
Use it only when no named tool answers the question: an unusual filter, a count, a pattern of
three or more hops, or a property the named tools do not return. A named tool is faster and
already filters bots, so try it first.

The tool runs your query read-only (a write is refused), for at most 5 seconds, and returns at
most `limit` rows (`truncated` is true when there were more). A query that fails comes back as
an error with FalkorDB's message: fix the query and try again, at most twice.

## Rules

1. **Return uids for every node you may cite**, aliased `AS uid` or `AS <thing>_uid`
   (`p.uid AS person_uid`, `w.uid AS uid`). Only uids that appear in rows can be cited. Also
   return a name (`title`, `login`, `name`) and `url`, so the answer can show them.
2. **Return properties, not whole nodes.** `RETURN w.uid AS uid, w.title AS title` is small;
   `RETURN w` sends every property, the full body included.
3. **Start from an index.** Look up one node by uid with `MATCH (n:Node {uid: $uid})`, or with
   its label (`MATCH (p:Person {login: $login})`). Take uids from earlier results; do not guess
   one. Indexed: `uid` on every label, `Person.login`,
   `System.name`, `WorkItem.number`, `WorkItem.key`, `WorkItem.url`. A pattern without a label or
   an indexed property scans the whole graph.
4. **Bound variable-length paths**: `[:BLOCKS*1..3]`, never `[*]`. Every query needs a `LIMIT`
   (the tool refuses one without), also a count: `RETURN count(n) AS n LIMIT 1`.
5. **Pass values as parameters** (`$login`, `$since`) in `params`, not pasted into the text.
6. **Read a node's kind** as `head([l IN labels(n) WHERE l <> 'Node'])`, never `labels(n)[0]`:
   every node also has the label `Node`, in any position.
7. **Leave out bots** when you count people's work: `WHERE NOT coalesce(p.is_bot, false)`.
8. **Do date math on the `*_ts` properties** (epoch seconds, integers). The `*_at` properties are
   ISO-8601 text for display. "Last 30 days": `WHERE w.created_ts >= $since` with
   `$since = <now epoch> - 30*86400`, or `timestamp() / 1000 - 30*86400` in the query.
9. Never return `embedding` (a vector of hundreds of numbers). The tool removes it anyway.
10. Do not use `shortestPath` (FalkorDB refuses undirected ones): use `algo.SPpaths` below.
    `LOAD CSV` is refused (so are the words `LOAD` and `CSV` together in the query text: put
    such a literal in `params`).

## Nodes

Every node has `uid`, `source` (the adapter that loaded it) and the extra label `Node`.

| Label | Properties | uid looks like |
|---|---|---|
| `Person` | `login`, `display_name`, `is_bot` | `person:<login>` |
| `Team` | `name` | `team:<name>` |
| `System` | `name`, `path_rule` (an area of the code, e.g. "Auth") | `system:<name>` |
| `WorkItem` | `kind`, `number`, `key`, `title`, `body`, `state`, `labels` (list), `container` (repo, team or channel), `url`, `created_at`/`created_ts`, `updated_at`, `closed_at`/`closed_ts`, `merged_at`; tickets also `status_category`, `priority`, `priority_rank`, `due_date`/`due_ts`; `unresolved_refs` (list) | `github:<owner>/<repo>:pr:<n>`, `github:<owner>/<repo>:issue:<n>`, `linear:issue:<id>`; find a ticket by `key`, a PR or issue by `number` |
| `Change` | a commit: `sha`, `subject`, `kind` (feat, fix, docs, build, …, other), `date`, `ts`, `url` | `github:<owner>/<repo>:commit:<sha>` |
| `Document` | `path`, `title`, `body`, `updated_at`, `url` | `github:<owner>/<repo>:doc:<path>` |
| `Chunk` | a piece of text for search: `kind` (`comment`, `work_item`, `document`), `text`, `idx`, `author_uid`, `comment_uid`, `created_at`, `ts`, `url` | `chunk:<uid>[:<idx>]` |
| `Claim` | a Keeper note: `kind`, `statement`, `value`, `status`, `valid_from`, `valid_to`, `approved_by` | `claim:…` |

`WorkItem.kind` and its `state` values:
- `pull_request`: `open`, `merged`, `closed`
- `issue`: `open`, `closed`
- `ticket` (Linear, key like `IDN-2`): `state` is the workspace's own name (`Todo`,
  `In Progress`, `Done`, `Canceled`, `Backlog`, …); use `status_category` to filter
  (`backlog`, `todo`, `in_progress`, `done`, `canceled`). `priority` is `urgent`, `high`,
  `medium`, `low`; `priority_rank` 1 (urgent) to 4 (low), 5 none.
- `thread`: a chat thread, `open`.

Archived items (older than the ingest window, loaded by the Archivist) also carry
`archived = true`, `archived_at`, `ref` and, when replaced, `superseded_by`.

A Claim in use has `status = 'accepted' AND valid_to IS NULL`. Treat it as a Keeper note, not a
source, and say so.

Internal labels, not about the company: `SyncState`, `Decision`, `Episode`. Do not query them.

## Relationships

| Pattern | Properties |
|---|---|
| `(Person)-[:AUTHORED]->(WorkItem \| Change \| Document)` | |
| `(Person)-[:REVIEWED]->(WorkItem)` (one per review) | `state` (APPROVED, CHANGES_REQUESTED, COMMENTED), `submitted_at`, `ts` |
| `(Person)-[:COMMENTED_ON]->(WorkItem)` (one per person and item) | `count`, `last_at`, `last_ts` |
| `(Person)-[:ASSIGNED_TO]->(WorkItem)` (tickets) | |
| `(Person)-[:MEMBER_OF]->(Team)` | |
| `(Person \| Team)-[:OWNS]->(System)` (declared, e.g. CODEOWNERS) | `pattern` |
| `(Change)-[:TOUCHES]->(System)` | `files` (count) |
| `(Change)-[:PART_OF]->(WorkItem)` (a commit of a PR) | |
| `(WorkItem)-[:CLOSES]->(WorkItem)` (a PR closes an issue) | |
| `(WorkItem)-[:BLOCKS]->(WorkItem)` (from the blocker to the blocked ticket) | |
| `(WorkItem \| Document)-[:MENTIONS]->(WorkItem \| System)` | |
| `(Chunk)-[:FROM]->(WorkItem \| Document)` | |
| `(Claim)-[:ABOUT]->(any node)`, `(Claim)-[:EVIDENCE]->(any node)` | |
| `(WorkItem \| Document)-[:SUPERSEDED_BY]->(WorkItem \| Document)` (archive) | |

The people who work on a system are found through commits:
`(p:Person)-[:AUTHORED]->(:Change)-[:TOUCHES]->(s:System)`. A PR's systems are
`(w)<-[:PART_OF]-(:Change)-[:TOUCHES]->(s)` or `(w)-[:MENTIONS]->(s)`.

A text can be cut into several chunks; `coalesce(c.idx, 0) = 0` keeps one per comment or body.

## FalkorDB procedures

- Full-text search (indexes on `WorkItem` and `Document`, fields `title` and `body`):
  `CALL db.idx.fulltext.queryNodes('WorkItem', $words) YIELD node, score`. `$words` is a
  RediSearch query: words joined by `|` match any (`'retry|idempotency'`).
- Shortest paths: `CALL algo.SPpaths({sourceNode: a, targetNode: b, relDirection: 'both',
  maxLen: 4, pathCount: 3}) YIELD path`.
These are for building a bigger query. When `related_work_items`, `related_documents`,
`path_between` or `central_nodes` already answers, use that tool: it also leaves bots out.

- PageRank over the whole graph: `CALL algo.pageRank(NULL, NULL) YIELD node, score`, then filter
  `WHERE node:System`. (Given a label, it follows only edges between nodes of that label.)
- Graph contents: `CALL db.labels()`, `CALL db.relationshipTypes()`, `CALL db.propertyKeys()`.
- For semantic (meaning) search, use the `semantic_search` tool: a query cannot embed text.

## Examples

Merged PRs that touched two given systems, newest first:

```cypher
MATCH (a:System {name: $a})<-[:TOUCHES]-(:Change)-[:PART_OF]->(w:WorkItem)
      <-[:PART_OF]-(:Change)-[:TOUCHES]->(b:System {name: $b})
WHERE w.state = 'merged'
RETURN DISTINCT w.uid AS uid, w.number AS number, w.title AS title, w.url AS url,
       w.closed_ts AS closed_ts
ORDER BY closed_ts DESC LIMIT 20
```

Open issues with no comments and no linked PR, oldest first:

```cypher
MATCH (w:WorkItem {kind: 'issue', state: 'open'})
WHERE NOT ()-[:COMMENTED_ON]->(w) AND NOT (:WorkItem)-[:CLOSES]->(w)
RETURN w.uid AS uid, w.number AS number, w.title AS title, w.url AS url, w.created_at AS created_at
ORDER BY w.created_ts LIMIT 20
```

Who reviewed one person's PRs, and how often (no bots):

```cypher
MATCH (a:Person {login: $login})-[:AUTHORED]->(w:WorkItem {kind: 'pull_request'})
      <-[r:REVIEWED]-(p:Person)
WHERE p <> a AND NOT coalesce(p.is_bot, false)
RETURN p.uid AS person_uid, p.login AS login, count(DISTINCT w) AS prs,
       collect(DISTINCT w.uid)[..5] AS uids
ORDER BY prs DESC LIMIT 10
```

Commits per kind on a system in the last 90 days:

```cypher
MATCH (c:Change)-[:TOUCHES]->(s:System {name: $system})
WHERE c.ts >= timestamp() / 1000 - 90 * 86400
RETURN s.uid AS system_uid, c.kind AS kind, count(c) AS commits
ORDER BY commits DESC LIMIT 20
```

Everything one ticket blocks, up to three steps, with who is assigned:

```cypher
MATCH (t:Node {uid: $uid})-[:BLOCKS*1..3]->(b:WorkItem)
OPTIONAL MATCH (p:Person)-[:ASSIGNED_TO]->(b)
RETURN DISTINCT b.uid AS uid, b.key AS key, b.title AS title, b.state AS state, b.url AS url,
       collect(DISTINCT p.login) AS assignees
LIMIT 25
```

Counts by kind of node (a quick look at what the graph holds):

```cypher
MATCH (n:Node)
RETURN head([l IN labels(n) WHERE l <> 'Node']) AS label, count(n) AS nodes
ORDER BY nodes DESC LIMIT 20
```
