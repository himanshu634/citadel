# Linear adapter (Jira later): design

**Status:** proposed, 2026-10-16. Plan: `docs/superpowers/plans/2026-10-16-linear-adapter.md`.

## 1. Goal

Bring ticket data (who has to do what, and what blocks what) into the company graph, so the agent
can answer questions like:

- "What does carol have to do?"
- "What is carol waiting on, and who has to move first?"
- "Who is waiting on alice?"

Every answer must come from graph paths with citations, like the current answers. Linear is the
first ticket source. Jira gets a written mapping (§6) and no code.

## 2. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | Linear is an ingestion adapter (`fetch` → cache → `records`), not an MCP server the agent calls at question time. | One graph, named tools, citations of graph uids. A live API call cannot join with GitHub data and its rows have no uids. |
| D2 | Tickets are `WorkItem {kind: "ticket"}`. No new node label. | Every existing tool (full-text search, `get_entity`, `path_between`, `recent_work_items`) works on tickets with no change. |
| D3 | The uid is the Linear issue `id`: `linear:issue:<id>`. The human key (`IDN-2`) goes in a new `key` property. | An identifier changes when an issue moves to another team. A uid built from it would make a second node. |
| D4 | Add a source-neutral `status_category` field (`backlog`, `todo`, `in_progress`, `done`, `canceled`). The raw `state` stays for display. | Tools must filter "open" the same way for Linear, Jira and later GitHub. |
| D5 | Assignment is a relationship, `(Person)-[:ASSIGNED_TO]->(WorkItem)`. It comes from a `WorkItem.assignees` field and is **replaced** each time the item loads. | When a ticket is reassigned, the old edge must go. MERGE alone would keep both. |
| D6 | Dependencies are `(WorkItem)-[:BLOCKS]->(WorkItem)`, a new link rel. After each ingest of a source, BLOCKS edges from that source that are no longer in its data are deleted. | A relation deleted in Linear must not stay in the graph. Links are always loaded in full from the cache, so the set that one source loads is complete. |
| D7 | Ticket ↔ PR: a Linear attachment URL becomes `(ticket)-[:MENTIONS]->(WorkItem)`. The target is found **by its `url`**, through `canonical.url_ref(url)` (`"url:<url>"`). | The Linear adapter does not need to know GitHub's uid format, and later sources (the Jira dev panel) can use the same mechanism. A link whose target is not in the graph is dropped and counted, as today. |
| D8 | An open ticket (`status_category` is not `done` or `canceled`) is always kept by the ingest window. Linear fetch pulls "updated in the window **or** open". | "What does X have to do" needs the backlog, including old tickets that nobody has touched. |
| D9 | People: login = Linear `displayName`, mapped to other logins with the existing `people.aliases`. Email is never requested in any `.graphql` file. | The same rules as today: no emails in `data/raw` or the graph. |
| D10 | Linear teams → `Team {name}` nodes, plus `MEMBER_OF` from the team's members. The team key (`IDN`) goes in `WorkItem.container`. | Linear team "Identity" is `team:identity`, the same node as the CODEOWNERS team `identity`. |
| D11 | Linear data is always private. Fetch refuses unless `data_permission` is `own` or `synthetic`. | Matches the private-repo rule of the GitHub adapter. |
| D12 | Synthetic tickets exist in two forms. One is JSONL (offline, used by tests and `make synthetic`). The other is a real Linear workspace, filled by a seeding command from the same JSONL and read by the real adapter under a **second** slug, `synthetic_linear`. | Offline answers that tests can check, plus a real import for the demo. Two slugs, because offline uids and live uids differ: one company with both forms would have every ticket twice. |
| D13 | Out of scope: sub-issues (parent/child), projects, cycles, ticket estimates, GitHub assignees, GitHub `status_category`, any frontend change. | Not needed for the three questions. Sub-issues would add `("PART_OF","WorkItem","WorkItem")` later. |

## 3. Graph model changes

**`WorkItem`, new properties** (all optional; GitHub items leave them null):

| Property | Type | Linear source |
|---|---|---|
| `key` | string, range index | `identifier` (`IDN-2`) |
| `status_category` | `backlog`/`todo`/`in_progress`/`done`/`canceled` | `state.type`: triage, backlog → backlog; unstarted → todo; started → in_progress; completed → done; canceled → canceled; any other value → todo |
| `priority` | `urgent`/`high`/`medium`/`low` or null | `priority`: 1 → urgent, 2 → high, 3 → medium, 4 → low, 0 → null |
| `priority_rank` | int, 1–4, 5 = none | derived by the loader, for sorting |
| `due_date` / `due_ts` | ISO date / epoch | `dueDate` |

New range index: `WorkItem.url` (for D7). Existing fields: `number` = Linear `number`; `state` =
`state.name`; `closed_at` = `completedAt` or `canceledAt`; `author_login` = `creator.displayName`;
`container` = `team.key`; `labels` = label names.

**New relationships**

| Relationship | Load query | Write rule |
|---|---|---|
| `(Person)-[:ASSIGNED_TO]->(WorkItem)` | `load/assigned_to` | For each loaded item with `assignees` not null: delete its ASSIGNED_TO edges, then MERGE one for each assignee. `assignees: []` means unassigned. `None` means the source does not track assignees, so edges are left as they are. |
| `(WorkItem)-[:BLOCKS {source, origin, uid}]->(WorkItem)` | `load/link_blocks` | MERGE. `origin` = the adapter key, for example `linear:synthetic-co`. Then `load/prune_blocks` deletes edges with that origin whose uid is not in this load. |
| `(WorkItem)-[:MENTIONS]->(WorkItem)` by url | `load/link_mentions_workitem_workitem_by_url` | MATCH the target by `url`. Used when `to_uid` starts with `url:`. |

`Link` rel `BLOCKS` is allowed only as `("BLOCKS","WorkItem","WorkItem")`. A `url:` reference is
allowed only on `to_uid`, and only for `("MENTIONS","WorkItem","WorkItem")`.

## 4. Linear adapter

```yaml
sources:
  - type: linear
    workspace: synthetic-co   # organization urlKey; fetch checks it against the API key's org
    teams: [IDN, PAY]         # team keys; empty = every team the key can read
```

- Key: `linear:<workspace>`. `LINEAR_API_KEY` in `.env`, sent as `Authorization: <key>` (no `Bearer`).
- Cache: `data/raw/<slug>/linear/<workspace>/`:
  - `meta.json`: org `urlKey`/name, fetched_at
  - `teams.json`: teams with members: id, key, name, `displayName`, `name`, `active`
  - `issues/`: resumable runs, the same `fetch_paged` as GitHub
- Issue query: `first: 25`, nested connections `first: 25`. This stays under the 10,000-point
  per-query complexity limit. Filter:
  `team.key in teams AND (updatedAt >= since OR state.type NOT IN [completed, canceled])`.
- Rate limits: HTTP 400 with `errors[].extensions.code == "RATELIMITED"`, or few requests left
  (`X-RateLimit-Requests-Remaining` < 50). In either case, sleep until
  `X-RateLimit-Requests-Reset` (epoch ms) and retry. 5xx: back off and retry.
- Records: `Person`, `Team`, `MEMBER_OF` links, ticket `WorkItem`s, `Comment`s, BLOCKS links
  (from both `relations` and `inverseRelations` of type `blocks`), MENTIONS links (`related`
  relations, and attachment URLs through `url_ref`). Relation type `duplicate` is ignored.
- Known limit: an issue with more than 25 comments, relations or attachments has only the first 25
  read.

## 5. Tools

| Tool | Answers | Rows |
|---|---|---|
| `open_work_for(login, limit=20)` | "What does X have to do?" | Open tickets assigned to X, sorted by `priority_rank`, then `due_ts` (nulls last), then `key`. Each row has its open blockers (`blocked_by`) and the open items waiting on it (`blocks`), as `{uid, key, title, url, status_category, assignees}`. |
| `blocked_on(login, limit=20)` | "What is X waiting on?" | For each open ticket of X: each open blocker up to 3 BLOCKS hops away. Fields: `depth`, `via` (the key of the next ticket in the chain), the blocker's assignees, and its linked PRs/issues (MENTIONS to a `WorkItem` that is not a ticket) with their state. A chain stops at any done or canceled ticket. |
| `waiting_on(login, limit=20)` | "Who is waiting on X?" | Open tickets of other people that X's open tickets block (directly), with their assignees. |

## 6. Jira (later, no code now)

The same canonical shape. A `jira` adapter would map:

| Canonical | Jira Cloud REST v3 |
|---|---|
| uid | `jira:<site>:issue:<id>` |
| `key` / `number` | `key` / its numeric part |
| `title` / `body` | `fields.summary` / `fields.description` (Atlassian Document Format → plain text) |
| `state` / `status_category` | `fields.status.name` / `fields.status.statusCategory.key`: `new` → todo, `indeterminate` → in_progress, `done` → done |
| `priority` | `fields.priority.name`: Highest → urgent, High → high, Medium → medium, Low/Lowest → low |
| `due_date` | `fields.duedate` |
| `assignees` / `author_login` | `fields.assignee` / `fields.reporter`. People are `accountId`s, so a company maps them to logins with `people.aliases`. |
| `container` | `fields.project.key` |
| BLOCKS | `fields.issuelinks` of type "Blocks", outward |
| MENTIONS | "Relates" links. PRs come from the dev-status panel API through `url_ref`. |
| Search | `GET /rest/api/3/search/jql` (the old `/search` is deprecated); auth is email + API token |

## 7. Synthetic tickets (known answers)

Linear teams: **Identity** (key `IDN`, members alice and carol) and **Payments** (key `PAY`, members
bob and erin). These are the members of today's synthetic teams, so no team membership changes.
dave and ci-bot get no tickets.

| Key | Title | Assignee | Status | Priority | Due | Blocked by | Linked |
|---|---|---|---|---|---|---|---|
| IDN-1 | Rotate JWT signing keys | alice | in_progress | high | | | |
| IDN-2 | SSO login for enterprise customers | carol | todo | urgent | 2026-11-06 | IDN-1, PAY-2 | |
| IDN-3 | Session audit log | carol | backlog | low | | | |
| IDN-4 | Extract token service | carol | done | medium | | | PR #10 |
| PAY-1 | Speed up invoice batch generation | bob | done | high | | | PR #4 |
| PAY-2 | Per-seat pricing for SSO plans | bob | in_progress | high | | PAY-3 | |
| PAY-3 | Usage-based add-ons | erin | in_progress | medium | 2026-10-30 | | PR #9 (open) |
| PAY-4 | Refunds in the web app | erin | todo | medium | | IDN-1 | |
| PAY-5 | Redesign old pricing page | bob | canceled | low | | | |
| PAY-6 | Invoice emails sent twice | erin | todo | high | | | issue #14 |

Expected answers:
- `open_work_for(carol)` = IDN-2, IDN-3.
- `open_work_for(erin)` = PAY-6, PAY-3, PAY-4.
- `open_work_for(alice)` = IDN-1, which blocks IDN-2 and PAY-4.
- `blocked_on(carol)`:
  - IDN-2 ← IDN-1 (alice, depth 1)
  - IDN-2 ← PAY-2 (bob, depth 1)
  - IDN-2 ← PAY-3 (erin, depth 2, via PAY-2, PR #9 open)
- `blocked_on(alice)` = none.
- `waiting_on(alice)` = IDN-2 (carol), PAY-4 (erin).
