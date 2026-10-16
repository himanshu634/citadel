# Linear adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import Linear tickets, their assignees and their `blocks` relations into `brain_<slug>`, and give the agent three tools that answer "what does X have to do", "what is X waiting on" and "who is waiting on X", with citations.

**Architecture:**
- **Graph schema:** the graph schema grows in a source-neutral way: new optional `WorkItem` fields, an `ASSIGNED_TO` relationship that is replaced on every load, a `BLOCKS` link that is pruned by origin, and links resolved by URL. Every ticket source (Linear now, Jira later) uses it.
- **Linear adapter:** a new `linear` adapter follows the GitHub pattern: a GraphQL client, resumable `fetch_paged` runs into `data/raw`, and a pure transform to canonical records.
- **Synthetic tickets:** they exist as JSONL (offline and in tests). A seeding command copies them into a real Linear workspace, which a second company slug reads through the adapter.

**Tech Stack:** Python 3.12, pydantic 2, httpx, FalkorDB (Cypher files under `apps/backend/queries/`), typer CLI, pytest.

**Spec:** `docs/superpowers/specs/2026-10-16-linear-adapter-design.md`. Read §2 (decisions D1–D13), §3 (graph model) and §7 (synthetic tickets and expected answers) before starting.

**Base branch:** `main`. Work in a git worktree: other sessions share the main checkout.

## Global Constraints

- **No Cypher in Python.** Each new query is a file under `apps/backend/queries/<folder>/<name>.cypher` with the `//` header (purpose / params / returns / example). It is fetched with `queries.get("load/x")`.
- **Load queries:** node writes set `company = $company` and `source`; edge writes set `source`. Everything is `MERGE` on uid, then `SET`.
- **No email addresses anywhere:**
  - No `.graphql` file requests an `email` field.
  - `Person.login` and `WorkItem.assignees` reject values that contain `@`.
- **Adapter rules:**
  - `fetch` writes only under its cache dir.
  - `records` does no network I/O; it raises `SourceUnavailable` when there is no cache.
- **Linear API:**
  - Endpoint `https://api.linear.app/graphql`; header `Authorization: <LINEAR_API_KEY>` (no `Bearer`).
  - Rate limit: HTTP 400 with `errors[].extensions.code == "RATELIMITED"`. Headers `X-RateLimit-Requests-Remaining` and `X-RateLimit-Requests-Reset` (epoch **milliseconds**).
  - Max 10,000 complexity points per query. Issue pages use `first: 25`, and nested connections use `first: 25`.
- **Code style:** ruff, line length 100, py312. Tests go in `apps/backend/tests/`.
- **Graph tests:** they use `needs_graph` or a session fixture from `conftest.py` and write only to `brain_test_*` graphs.
- **Agent prompt:** `agents/system_prompt.md` stays static (no dates). Tools are registered in `tools.TOOLS`; the toolset sorts them.
- **Jira:** no code. No `jira` entry in `adapters.REGISTRY`.

## Review Focus

1. **An issue moves teams in Linear** (`IDN-3` becomes `PAY-7`, same `id`). The graph keeps one node, with the newest `key` and `container`. (Task 6, `test_team_move_keeps_one_node`)
2. **An assignee who left the workspace, or no assignee at all.** Linear returns `assignee: null`, so the ticket loads with `assignees=[]` and any old edge is removed. No crash and no Person named `None`. (Tasks 2 and 6)
3. **A blocker outside the configured teams or outside the cache.** The BLOCKS link is dropped and counted by the loader. Ingest does not fail. (Task 6, `test_blocker_outside_cache_is_a_dangling_link`)
4. **A partial ingest of another source** (`make ingest SOURCE=canonical_jsonl`). It must not prune Linear's BLOCKS edges, because pruning is scoped by `origin`. (Task 2, `test_prune_only_touches_its_origin`)
5. **The API key belongs to another workspace than `workspace:` in the YAML.** Fetch and seed both refuse before writing anything. (Tasks 5 and 9)

## File Structure

```
apps/backend/
  brain/
    canonical.py                     modify: WorkItem fields, BLOCKS, url_ref
    normalize.py                     modify: assignees, open tickets ignore the window
    loader.py                        modify: new props, ASSIGNED_TO, BLOCKS + prune, url links, origin
    pipeline.py                      modify: pass origin=key to loader.load
    config.py                        modify: Settings.linear_api_key
    tools.py                         modify: open_work_for, blocked_on, waiting_on
    cli.py                           modify: `brain linear-seed`
    agents/system_prompt.md          modify: new relationships + ticket tools line
    adapters/
      __init__.py                    modify: register "linear"
      runs.py                        create: fetch_paged, completed_pages, json/time helpers (moved)
      github/fetch.py                modify: import + re-export from runs
      linear/__init__.py             create: LinearSource, LinearAdapter
      linear/client.py               create: LinearClient, LinearError, LinearRateLimited, token
      linear/fetch.py                create: run()
      linear/transform.py            create: records()
      linear/seed.py                 create: load_seed(), seed()
      linear/queries/*.graphql       create: meta, teams, issues, seed_lookup, issue_create,
                                             relation_create, attachment_create
  queries/
    load/work_item.cypher            modify: key, status_category, priority, priority_rank, due_*
    load/assigned_to.cypher          create
    load/link_blocks.cypher          create
    load/prune_blocks.cypher         create
    load/link_mentions_workitem_workitem_by_url.cypher   create
    schema/range_indexes.cypher      modify: WorkItem.key, WorkItem.url
    tools/open_work_for.cypher       create
    tools/blocked_on.cypher          create
    tools/waiting_on.cypher          create
  examples/synthetic_company/
    generate.py                      modify: TICKETS, writes tickets/
    tickets/                         create (generated): work_items.jsonl, links.jsonl, linear_seed.json
  tests/
    test_canonical.py                create
    test_normalize.py                modify
    test_loader_tickets.py           create (graph)
    test_runs.py                     create
    test_linear_client.py            create
    test_linear_fetch.py             create
    test_linear_adapter.py           create
    test_linear_seed.py              create
    test_ticket_tools.py             create (graph)
    conftest.py                      modify: with_tickets, ticket_graph
    fixtures/linear/synthetic-co/    create: meta.json, teams.json, issues/state.json + page
    fixtures/linear/README.md        create
companies/synthetic.yaml             modify: second canonical_jsonl source (tickets)
companies/synthetic_linear.yaml      create
docs/graph-model.md, docs/canonical-format.md, docs/adding-a-company.md   modify
.env.example, Makefile               modify
```

---

### Task 1: Canonical ticket fields and normalize rules

**Files:**
- Modify: `apps/backend/brain/canonical.py`, `apps/backend/brain/normalize.py`, `docs/canonical-format.md`
- Test: `apps/backend/tests/test_canonical.py` (create), `apps/backend/tests/test_normalize.py`

**Interfaces:**
- Produces, in `brain.canonical`:
  - Type aliases:
    - `StatusCategory = Literal["backlog", "todo", "in_progress", "done", "canceled"]`
    - `CLOSED_STATUS: frozenset[str] = frozenset({"done", "canceled"})`
    - `Priority = Literal["urgent", "high", "medium", "low"]`
  - New `WorkItem` fields:
    - `key: str | None = None`
    - `status_category: StatusCategory | None = None`
    - `priority: Priority | None = None`
    - `due_date: date | None = None`
    - `assignees: list[str] | None = None` (None = the source doesn't track assignees; [] = unassigned)
  - `WorkItem.is_open_ticket() -> bool`: `status_category is not None and status_category not in CLOSED_STATUS`.
  - `LinkRel` gains `"BLOCKS"`, and `ALLOWED_LINKS` gains `("BLOCKS", "WorkItem", "WorkItem")`.
  - URL references:
    - `URL_PREFIX = "url:"`
    - `URL_LINKS: set[tuple[str, str, str]] = {("MENTIONS", "WorkItem", "WorkItem")}`
    - `url_ref(url: str) -> str` (returns `"url:" + url`)
    - `is_url_ref(uid: str) -> bool`

- [ ] **Step 1: Write the failing tests** in `test_canonical.py`:
  - `test_blocks_link_only_between_work_items`: Link BLOCKS WorkItem→WorkItem validates; BLOCKS WorkItem→System raises `ValidationError`.
  - `test_url_ref_only_as_mentions_target`: `Link(rel="MENTIONS", from_label="WorkItem", to_label="WorkItem", from_uid="a", to_uid=url_ref("https://x/pull/1"))` validates. The same `to_uid` with `rel="CLOSES"` raises, and `from_uid=url_ref(...)` raises.
  - `test_assignee_cannot_be_an_email`: `WorkItem(..., assignees=["a@b.co"])` raises.
  - `test_is_open_ticket`: `todo` → True, `in_progress` → True, `done` → False, `canceled` → False, None → False.

  In `test_normalize.py`:
  - `test_assignees_are_aliased_and_people_derived`: with `people.aliases={"Alice K": "alice"}`, a ticket with `assignees=["Alice K"]` comes out with `["alice"]`, and a derived `Person(login="alice")` is yielded.
  - `test_assignees_none_stays_none`
  - `test_open_ticket_outside_window_is_kept`: `status_category="todo"`, created 2025-01-01, window 2026-01-01 → yielded.
  - `test_closed_ticket_outside_window_is_dropped`: the same with `done` → not yielded.

- [ ] **Step 2: Run them, expect failures:** `make test ARGS="apps/backend/tests/test_canonical.py apps/backend/tests/test_normalize.py"`.
- [ ] **Step 3: Implement the canonical additions.** The Link validator rejects a url ref in `from_uid`, and rejects a url ref in `to_uid` unless `(rel, from_label, to_label) in URL_LINKS`. The `assignees` validator rejects any entry that contains `@`.
- [ ] **Step 4: Implement the normalize changes.** In the `WorkItem` branch:
  - `clean_item` maps each assignee through `login()` (None stays None).
  - An item with `rec.is_open_ticket()` is yielded whatever its dates are, before the existing window check.
- [ ] **Step 5: Run the tests, expect them to pass.** Also run `make test ARGS=apps/backend/tests/test_github_adapter.py`; it must still pass.
- [ ] **Step 6: Update `docs/canonical-format.md`:** the new WorkItem fields, `assignees` None vs [], BLOCKS, and `url_ref`. Then commit:

```bash
git add apps/backend/brain/canonical.py apps/backend/brain/normalize.py docs/canonical-format.md apps/backend/tests/test_canonical.py apps/backend/tests/test_normalize.py
git commit -m "Canonical ticket fields: status_category, priority, due date, assignees, BLOCKS, url refs"
```

### Task 2: Loader, load queries and indexes for tickets

**Files:**
- Modify: `apps/backend/brain/loader.py`, `apps/backend/brain/pipeline.py`, `apps/backend/queries/load/work_item.cypher`, `apps/backend/queries/schema/range_indexes.cypher`, `docs/graph-model.md`
- Create: `queries/load/assigned_to.cypher`, `queries/load/link_blocks.cypher`, `queries/load/prune_blocks.cypher`, `queries/load/link_mentions_workitem_workitem_by_url.cypher`
- Test: `apps/backend/tests/test_loader_tickets.py` (create), `apps/backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: Task 1's `WorkItem` fields, `url_ref`, `is_url_ref`, `URL_LINKS`.
- Produces:
  - `loader.load(slug, records, origin: str | None = None) -> LoadReport`. With `origin`, BLOCKS edges get `r.origin = origin` and are pruned after the links are written.
  - `loader.PRIORITY_RANK = {"urgent": 1, "high": 2, "medium": 3, "low": 4}`; None ranks 5.
  - `loader.URL_LINK_QUERIES = {("MENTIONS", "WorkItem", "WorkItem"): "load/link_mentions_workitem_workitem_by_url"}`
  - Graph properties: `WorkItem.key`, `status_category`, `priority`, `priority_rank`, `due_date` (ISO date), `due_ts` (epoch).
  - Graph edges: `(Person)-[:ASSIGNED_TO]->(WorkItem)` and `(WorkItem)-[:BLOCKS {source, origin, uid}]->(WorkItem)`.

**Query contracts:**
- `assigned_to`:
  - Rows `[{work_item_uid, person_uids}]`, sent only for items whose `assignees is not None`.
  - For each row: MATCH the item, delete every incoming `ASSIGNED_TO`, then MERGE one from each existing Person in `person_uids`.
  - Returns `n` = items matched.
- `link_blocks`: rows `{from_uid, to_uid, source, origin, uid}` (uid = `Link.uid`). Returns `n` = edges.
- `prune_blocks`:
  - Params `$origin`, `$keep` (list of link uids).
  - Deletes `()-[r:BLOCKS {origin: $origin}]->()` where `NOT r.uid IN $keep`.
  - Returns `n` = deleted.
- `..._by_url`:
  - Rows `{from_uid, to_url, source}`, where `to_url` is the `to_uid` without its `url:` prefix.
  - MATCH `(b:WorkItem {url: row.to_url})`.

- [ ] **Step 1: Write the failing tests.**

  `test_loader_tickets.py` uses `needs_graph` and a throwaway slug `test_tickets`, deleted in a fixture. Each test loads small handcrafted records with `loader.load` after `schema.apply_schema`:
  - `test_ticket_properties_written`: `priority="urgent"` → `priority_rank` 1; `priority=None` → 5; `due_date=date(2026,11,6)` → `due_date == "2026-11-06"` and `due_ts == 1793923200`.
  - `test_reassigning_replaces_assignee`: load with `["alice"]`, then with `["bob"]` → exactly one ASSIGNED_TO, and it comes from bob.
  - `test_unassigning_removes_edge`: `["alice"]` then `[]` → zero edges.
  - `test_assignees_none_keeps_edges`: `["alice"]` then `None` → one edge, from alice.
  - `test_prune_only_touches_its_origin`:
    1. Load `A BLOCKS B` with `origin="linear:x"`, and `C BLOCKS D` with `origin="other"`.
    2. Reload origin `linear:x` with no BLOCKS links → A→B is gone and C→D remains.
  - `test_load_without_origin_never_prunes`
  - `test_mentions_by_url_resolves_target`: a ticket `MENTIONS url_ref(pr.url)` → an edge to the PR. A url no WorkItem has → `report.dropped["load/link_mentions_workitem_workitem_by_url"] == 1`.

  Unit tests (no graph) in the same file:
  - `test_link_queries_cover_allowed_links`: `set(LINK_QUERIES) == ALLOWED_LINKS` and `set(URL_LINK_QUERIES) == URL_LINKS`.

  In `test_pipeline.py`:
  - `test_ingest_passes_source_key_as_origin`: monkeypatch `loader.load` to capture `origin`. It must equal the adapter key.

- [ ] **Step 2: Run them, expect failures:** `make up && make test ARGS=apps/backend/tests/test_loader_tickets.py`.
- [ ] **Step 3: Write the four new `.cypher` files** to the contracts above. Extend `work_item.cypher` (header `params` line included). Add `CREATE INDEX FOR (n:WorkItem) ON (n.key);` and `... ON (n.url);` to `range_indexes.cypher`.
- [ ] **Step 4: Change `loader.load`.**
  1. The work item rows carry the new properties.
  2. An `assigned_to` step runs after authorship.
  3. Links are split: a `to_uid` that is a url ref goes to `URL_LINK_QUERIES` and the rest go to `LINK_QUERIES`. BLOCKS rows carry `uid` and `origin`.
  4. After all links, when `origin` is given, run `load/prune_blocks` with `keep` = the uids of this load's BLOCKS links (an empty list is valid).

  In `pipeline.ingest`, pass `origin=key`.
- [ ] **Step 5: Run the tests, expect them to pass.** Run the whole suite as well (`make test`); the existing graph tests must still pass.
- [ ] **Step 6: Update `docs/graph-model.md`:**
  - the mermaid diagram (ASSIGNED_TO, BLOCKS)
  - the WorkItem row
  - the relationship table, with the replace and prune rules from spec §3
  - the indexes list
  - an "Ingest window" sentence for open tickets

  Then commit:

```bash
git add apps/backend/brain/loader.py apps/backend/brain/pipeline.py apps/backend/queries docs/graph-model.md apps/backend/tests/test_loader_tickets.py apps/backend/tests/test_pipeline.py
git commit -m "Loader: ticket properties, replaced ASSIGNED_TO, BLOCKS pruned by origin, links by url"
```

### Task 3: Shared resumable paging (`adapters/runs.py`)

**Files:**
- Create: `apps/backend/brain/adapters/runs.py`
- Modify: `apps/backend/brain/adapters/github/fetch.py` (import from `runs` and re-export, so `github/transform.py` and other importers keep working)
- Test: `apps/backend/tests/test_runs.py` (create)

**Interfaces:**
- Produces, in `brain.adapters.runs`, the code moved unchanged from `github/fetch.py`:
  - `OVERLAP`
  - `iso(dt) -> str`, `parse_ts(value) -> datetime`
  - `read_json(path, default=None)`, `write_json(path, data)`
  - `fetch_paged(client: PagedClient, query, variables, connection, folder, window_start, stop_when_older=None, send_since=True, incremental=True, log=print) -> int`
  - `completed_pages(folder) -> list[Path]`
  - `class PagedClient(Protocol): def query(self, name: str, variables: dict[str, Any]) -> dict: ...`

- [ ] **Step 1: Write the failing tests** in `test_runs.py`, with a `FakeClient` that serves canned pages (`{"x": {"nodes": [...], "pageInfo": {"hasNextPage": ..., "endCursor": ...}}}`):
  - `test_fetch_paged_writes_pages_and_completes_run`: two pages → two files, and `state.json` has one completed run.
  - `test_unfinished_run_is_resumed_from_its_cursor`: the client raises on page 2; a second call starts with `after == <page-1 cursor>`.
  - `test_completed_pages_skip_unfinished_runs`
  - `test_send_since_passes_run_lower_bound`
- [ ] **Step 2: Run them, expect an `ImportError`:** `make test ARGS=apps/backend/tests/test_runs.py`.
- [ ] **Step 3: Move the code.** `github/fetch.py` does `from brain.adapters.runs import OVERLAP, completed_pages, fetch_paged, iso, parse_ts, read_json, write_json` and keeps using them.
- [ ] **Step 4: Run the tests and `make test ARGS="apps/backend/tests/test_github_adapter.py apps/backend/tests/test_github_client.py"`.** All pass. `make lint` passes.
- [ ] **Step 5: Commit:** `git commit -m "Move resumable paged fetching to adapters/runs for reuse"`.

### Task 4: Linear client, source config and GraphQL documents

**Files:**
- Create: `apps/backend/brain/adapters/linear/__init__.py` (LinearSource only for now), `linear/client.py`, `linear/queries/meta.graphql`, `teams.graphql`, `issues.graphql`
- Modify: `apps/backend/brain/config.py` (`linear_api_key: str | None = None`, added to `_empty_is_none`), `.env.example`
- Test: `apps/backend/tests/test_linear_client.py` (create)

**Interfaces:**
- Produces:
  - `LinearSource(SourceConfig)`:
    - `type: Literal["linear"]`
    - `workspace: str`, pattern `^[a-z0-9-]+$`
    - `teams: list[str] = []`, each matching `^[A-Z][A-Z0-9]{0,6}$`
  - `client.API = "https://api.linear.app/graphql"`, `LOW_REQUESTS = 50`
  - `class LinearError(RuntimeError)`, `class LinearRateLimited(LinearError)`
  - `token() -> str`. Raises `LinearError("no Linear API key: set LINEAR_API_KEY in .env")`.
  - `LinearClient(log=print, *, timeout: float = 60, attempts: int = 5, transport: httpx.BaseTransport | None = None)`
    - context manager
    - `query(name: str, variables: dict, document: str | None = None) -> dict` returns `data`
  - GraphQL documents:
    - `meta`: `viewer { organization { urlKey name } }`
    - `teams`: `teams(first: 50) { nodes { id key name members(first: 100) { nodes { id displayName name active } } } }`
    - `issues($teams: [String!]!, $since: DateTimeOrDuration!, $first: Int!, $after: String)`
      - Filter: `{team: {key: {in: $teams}}, or: [{updatedAt: {gte: $since}}, {state: {type: {nin: ["completed", "canceled"]}}}]}`, `orderBy: updatedAt`.
      - Node fields: `id identifier number title description url priority dueDate createdAt updatedAt completedAt canceledAt`, plus:
        - `state { name type }`
        - `team { key name }`
        - `creator { displayName }`
        - `assignee { displayName }`
        - `labels(first: 25) { nodes { name } }`
        - `relations(first: 25) { nodes { type relatedIssue { id } } }`
        - `inverseRelations(first: 25) { nodes { type issue { id } } }`
        - `attachments(first: 25) { nodes { url title } }`
        - `comments(first: 25) { nodes { id body createdAt user { displayName } } }`
      - `pageInfo { hasNextPage endCursor }`.

- [ ] **Step 1: Write the failing tests** (`httpx.MockTransport`, `time.sleep` monkeypatched to record its argument):
  - `test_sends_key_without_bearer`: the request header `Authorization` equals the key exactly.
  - `test_ratelimited_400_waits_until_reset_then_retries`: the first response is 400 with `errors[0].extensions.code == "RATELIMITED"` and `X-RateLimit-Requests-Reset` = now+30 s in ms. The second response is 200. Sleep is called with about 31 s, and the data is returned.
  - `test_low_remaining_sleeps_after_success`: `X-RateLimit-Requests-Remaining: 10` → sleeps until reset.
  - `test_5xx_backs_off_then_raises_after_attempts`
  - `test_graphql_error_raises_linear_error`
  - `test_missing_key_message`
  - `test_no_query_requests_email`: no `.graphql` under `adapters/linear/queries/` contains the word `email`.
  - `test_source_rejects_bad_workspace_and_team_keys`
- [ ] **Step 2: Run them, expect failures:** `make test ARGS=apps/backend/tests/test_linear_client.py`.
- [ ] **Step 3: Implement `client.py`, `LinearSource` and the three `.graphql` files.** Base the client on `github/client.py` (same docstring style), but with the rate-limit rules from Global Constraints. Add to `.env.example`, under GitHub: `LINEAR_API_KEY=`, with a comment that it is a personal API key from Linear → Settings → Security & access, and that it is only needed for `linear` sources and `make linear-seed`.
- [ ] **Step 4: Run the tests, expect them to pass.**
- [ ] **Step 5: Commit:** `git commit -m "Linear GraphQL client, source config and query documents"`.

### Task 5: Linear fetch

**Files:**
- Create: `apps/backend/brain/adapters/linear/fetch.py`
- Test: `apps/backend/tests/test_linear_fetch.py` (create)

**Interfaces:**
- Consumes: `LinearClient`, `fetch_paged`, `write_json`, `iso`.
- Produces: `run(company: CompanyConfig, source: LinearSource, cache: Path, client: PagedClient | None = None, log=print) -> None`, which writes `meta.json`, `teams.json` and `issues/`. It also provides:
  - `check_permission(company) -> None`: raises `PermissionError` unless `data_permission in ("own", "synthetic")`, with a message naming `companies/<slug>.yaml`.

- [ ] **Step 1: Write the failing tests** (FakeClient keyed by query name, `tmp_path` cache):
  - `test_refuses_public_company`: raises before any file is written.
  - `test_refuses_other_workspace`: org urlKey `acme` vs `workspace: synthetic-co` → `RuntimeError` mentioning both. The cache dir stays empty.
  - `test_unknown_team_key_refuses`: `teams: [IDN, OPS]`, where the workspace has only IDN.
  - `test_writes_meta_teams_and_issue_pages`:
    - `meta.json` has `urlKey` and `fetched_at`.
    - `teams.json` holds only the configured teams.
    - The `issues/` run completed.
    - The client got `teams == ["IDN", "PAY"]` and `first == 25`.
  - `test_empty_teams_means_every_team`
- [ ] **Step 2: Run them, expect failures.**
- [ ] **Step 3: Implement `run`.** The order is: permission → meta (write, then compare urlKey) → teams (filter, error on a missing key) → `fetch_paged(client, "issues", {"teams": keys, "first": 25}, lambda d: d["issues"], cache / "issues", window_start=<window.since at 00:00 UTC>)`. When `client` is None, open a `LinearClient` and close it.
- [ ] **Step 4: Run the tests, expect them to pass.**
- [ ] **Step 5: Commit:** `git commit -m "Linear fetch: permission and workspace checks, teams snapshot, resumable issue runs"`.

### Task 6: Linear transform and registration

**Files:**
- Create: `apps/backend/brain/adapters/linear/transform.py`, `tests/fixtures/linear/synthetic-co/{meta.json,teams.json,issues/state.json,issues/20261016T000000_0000.json,issues/20261016T120000_0000.json}`, `tests/fixtures/linear/README.md`
- Modify: `linear/__init__.py` (add `LinearAdapter`), `apps/backend/brain/adapters/__init__.py`
- Test: `apps/backend/tests/test_linear_adapter.py` (create)

**Interfaces:**
- Consumes: Task 1 records, `completed_pages`, `read_json`, `check_permission` (Task 5).
- Produces:
  - `records(company, source, cache) -> Iterator[CanonicalRecord]`
  - `issue_uid(id: str) -> str` (`"linear:issue:<id>"`)
  - `STATUS_MAP`, `PRIORITY_MAP` (values from spec §3)
  - `LinearAdapter` (`name = "linear"`, `key(source) == f"linear:{source.workspace}"`, `cache_for(source, cache_dir) == cache_dir / source.workspace`), registered as `REGISTRY["linear"]`

**Mapping** (spec §3 and §4):
- **Issues:** each issue appears once, from its latest page (later runs win). It becomes `WorkItem(kind="ticket", source="linear")` with:
  - `number`, `key=identifier`, `title`, `body=description or ""`
  - `state=state.name`, `status_category`, `priority`
  - `due_date`, `created_at`, `updated_at`, `closed_at=completedAt or canceledAt`
  - `author_login=creator.displayName`
  - `assignees=[assignee.displayName]`, or `[]` when there is no assignee
  - `labels`, `container=team.key`, `url`
- **Comments:** `Comment(uid=f"linear:comment:{id}")`. Skipped when `user` is null.
- **People and teams:** for each team member, `Person(login=displayName, display_name=name)`. `Team(name=team.name)` per team, plus `MEMBER_OF` for active members.
- **BLOCKS:** from `relations` of type `blocks` (this → related) and from `inverseRelations` of type `blocks` (other → this).
- **MENTIONS:**
  - from `relations` of type `related`
  - from each attachment `url`, as `url_ref(url)`

  Other relation types are ignored.

The fixture is hand-written in API shape, with two completed runs. It covers:
- an assigned ticket and an unassigned one
- blocks through `relations` only and through `inverseRelations` only
- `related` and `duplicate` relations
- an attachment
- a comment with `user: null`
- state types `triage` and `weird_new_type`
- priority 0, a `dueDate`
- an issue whose second-run page has another identifier and team (a team move)
- a blocker id that is not in the cache

- [ ] **Step 1: Write the failing tests** against `FIXTURE = tests/fixtures/linear/synthetic-co`:
  - `test_ticket_fields`: one known issue, with every mapped field asserted, including `due_date == date(...)` and `status_category`.
  - `test_status_and_priority_maps`: `triage` → backlog, `weird_new_type` → todo, priority 0 → None.
  - `test_unassigned_is_empty_list`
  - `test_blocks_from_both_directions_once`: the set of `(from, to)` BLOCKS pairs is exactly the expected set.
  - `test_duplicate_relation_ignored`
  - `test_attachment_is_url_mention`
  - `test_comment_without_user_skipped`
  - `test_team_move_keeps_one_node`: one WorkItem for that id, with the second run's key and container.
  - `test_blocker_outside_cache_is_a_dangling_link`: the link is emitted. Loading it, in a `needs_graph` sub-test, reports it under `dropped`.
  - `test_members_and_teams`
  - `test_no_email_in_records`: no string field of any record contains `@`.
  - `test_no_cache_raises_source_unavailable`
  - `test_registered_and_yaml_validates`: `CompanyConfig.model_validate` with a `linear` source works.
- [ ] **Step 2: Run them, expect failures.**
- [ ] **Step 3: Implement `transform.py` and `LinearAdapter`, and register it.** Write the fixture files and a README. The README says: hand-written in API shape; re-record from a real workspace in Task 10.
- [ ] **Step 4: Run the tests, then the full suite, and expect them to pass.**
- [ ] **Step 5: Commit:** `git commit -m "Linear transform: tickets, assignees, blocks, attachments, members; register adapter"`.

### Task 7: Synthetic tickets (offline)

**Files:**
- Modify: `apps/backend/examples/synthetic_company/generate.py`, `companies/synthetic.yaml`, `apps/backend/tests/conftest.py`
- Create (generated): `apps/backend/examples/synthetic_company/tickets/work_items.jsonl`, `links.jsonl`, `linear_seed.json`
- Test: `apps/backend/tests/test_ticket_tools.py` (create; this task adds only the data test)

**Interfaces:**
- Produces:
  - Ticket records with `uid = f"synthetic:ticket:{key}"`, `url = f"https://example.com/synthetic/linear/{key}"`, `number` = the numeric part of the key, `container` = `IDN` or `PAY`, `author_login` = `alice` (IDN) or `bob` (PAY), `assignees`, `status_category`, `priority`, `due_date` and `state` exactly as in spec §7.
    - Raw `state` names: Backlog, Todo, In Progress, Done, Canceled.
    - `created_at` / `closed_at`: IDN-1 2026-09-15; IDN-2 2026-09-20; IDN-3 2026-08-01; IDN-4 2026-08-25 / 2026-09-01; PAY-1 2026-04-01 / 2026-04-20; PAY-2 2026-09-05; PAY-3 2026-08-18; PAY-4 2026-09-25; PAY-5 2026-07-10 / 2026-07-15; PAY-6 2026-09-11.
  - `links.jsonl`:
    - BLOCKS: IDN-1→IDN-2, PAY-2→IDN-2, PAY-3→PAY-2, IDN-1→PAY-4
    - MENTIONS: IDN-4→`synthetic:pr:10`, PAY-1→`synthetic:pr:4`, PAY-3→`synthetic:pr:9`, PAY-6→`synthetic:issue:14`
  - `linear_seed.json`: `{"teams": {"IDN": "Identity", "PAY": "Payments"}}`
  - `conftest.synthetic_company(slug, folder=SYNTHETIC, with_tickets: bool = False)`. `load_company(cfg)` loads **every** source. Session fixture `ticket_graph` uses slug `test_tickets_synth`. `synthetic_graph` is unchanged, so existing expected answers hold.

- [ ] **Step 1: Write the failing test** `test_synthetic_tickets_validate` (no graph): `CanonicalJsonlAdapter` reads `tickets/` → 10 ticket WorkItems, 4 BLOCKS links and 4 MENTIONS links. Every MENTIONS target uid exists in the base `work_items.jsonl`.
- [ ] **Step 2: Run it, expect a failure** (the folder doesn't exist yet).
- [ ] **Step 3: Extend `generate.py`.** Add a `TICKETS` table, update the module docstring's list of known answers to spec §7's expected answers, and write the `tickets/` folder. Run `uv run python apps/backend/examples/synthetic_company/generate.py`. Add `- type: canonical_jsonl` with `path: apps/backend/examples/synthetic_company/tickets` to `companies/synthetic.yaml`. Update `conftest.py`.
- [ ] **Step 4: Run the test, then `make test` and `make synthetic`.** All pass, and `make stats` shows ASSIGNED_TO 10 and BLOCKS 4.
- [ ] **Step 5: Commit:** `git commit -m "Synthetic company: ten tickets with assignees, blockers and PR links"`.

### Task 8: Ticket tools for the agent

**Files:**
- Create: `apps/backend/queries/tools/open_work_for.cypher`, `blocked_on.cypher`, `waiting_on.cypher`
- Modify: `apps/backend/brain/tools.py`, `apps/backend/brain/agents/system_prompt.md`
- Test: `apps/backend/tests/test_ticket_tools.py`

**Interfaces:**
- Consumes: graph from Tasks 2 and 7. `LinkRef` and `_person` already exist in `tools.py`.
- Produces, in `brain.tools`:
  - `WorkParams(PersonParams)`, with `limit: int = Field(20, ge=1, le=100)`.
  - Row models:
    - `TicketRef(uid, key: str | None, title, url: str | None, status_category: str | None, assignees: list[str])`
    - `OpenWork(person_uid, uid, key, title, url, state, status_category, priority: str | None, due_date: str | None, container: str | None, blocked_by: list[TicketRef], blocks: list[TicketRef])`
    - `Blocker(person_uid, ticket: TicketRef, blocker: TicketRef, depth: int, via: str | None, linked: list[LinkRef])`
    - `Waiting(person_uid, mine: TicketRef, waiting: TicketRef)`
  - Tools `open_work_for`, `blocked_on`, `waiting_on`, each with `prepare=_person`, and typed wrappers of the same names: `(slug, login, limit=20) -> list[Row]`.
  - Descriptions:
    - "Open tickets assigned to a person, most urgent first, with what blocks them and what they block."
    - "What a person's open tickets are waiting on: open blockers up to three steps away, who owns each, and linked PRs."
    - "Other people's open tickets that are blocked by a person's open tickets."

**Query semantics** (spec §5):
- "Open" means `status_category IS NOT NULL AND NOT status_category IN ['done', 'canceled']`.
- `blocked_on` uses `(b:WorkItem)-[:BLOCKS*1..3]->(t)`, requires every node on the path to be open, takes the shortest `depth` for each (t, b), and sets `via` to the key of the node after `b`. When `depth == 1`, `via` is null. Sort: ticket key, depth, blocker key.
- `linked` = `(b)-[:MENTIONS]->(x:WorkItem)` where `x.kind <> 'ticket'`.
- `open_work_for` sort: `priority_rank`, then `due_ts` with nulls last, then `key`.

- [ ] **Step 1: Write the failing tests** (`ticket_graph`), using the expected answers from spec §7:
  - `test_open_work_for_carol`: keys `["IDN-2", "IDN-3"]`; the `blocked_by` keys of IDN-2 are `{"IDN-1", "PAY-2"}`.
  - `test_open_work_for_erin_sort_order`: `["PAY-6", "PAY-3", "PAY-4"]`.
  - `test_open_work_for_alice_lists_what_it_blocks`: `["IDN-1"]`, with blocks `{"IDN-2", "PAY-4"}`.
  - `test_blocked_on_carol`: `(ticket, blocker, depth, via)` = `{("IDN-2","IDN-1",1,None), ("IDN-2","PAY-2",1,None), ("IDN-2","PAY-3",2,"PAY-2")}`. The PAY-3 row has `linked` with uid `synthetic:pr:9` and state `open`.
  - `test_blocked_on_alice_is_empty`
  - `test_waiting_on_alice`: `{("IDN-1","IDN-2"), ("IDN-1","PAY-4")}`.
  - `test_done_blocker_breaks_chain`: a throwaway slug with handcrafted records, where A (open, alice) is blocked by B (done), which is blocked by C (open). `blocked_on(alice) == []`.
  - `test_ticket_rows_are_citable`: `Toolset(TOOLS, call).call(slug, "blocked_on", {"login": "carol"}).seen` contains `synthetic:ticket:PAY-3` (with its title) and `synthetic:pr:9`.
- [ ] **Step 2: Run them, expect failures.**
- [ ] **Step 3: Write the three `.cypher` files** (with headers) and the models and registrations in `tools.py`. In `system_prompt.md`, add these lines to the relationship list:
  - ``- `(Person)-[:ASSIGNED_TO]->(WorkItem)`, `(WorkItem)-[:BLOCKS]->(WorkItem)` (tickets)``

  Add this line under "How to work":
  - ``- Tickets are WorkItems of kind `ticket` with keys like `IDN-2`. Use `open_work_for` for what someone has to do, `blocked_on` for what they are waiting on and `waiting_on` for who waits on them.``
- [ ] **Step 4: Run the tests, then `make test` and `make query SLUG=synthetic TOOL=blocked_on P="login=carol"`.** All pass. The query prints the three rows.
- [ ] **Step 5: Commit:** `git commit -m "Ticket tools: open_work_for, blocked_on, waiting_on"`.

### Task 9: Seed a real Linear workspace, and the live company

**Files:**
- Create: `apps/backend/brain/adapters/linear/seed.py`, `linear/queries/seed_lookup.graphql`, `issue_create.graphql`, `relation_create.graphql`, `attachment_create.graphql`, `companies/synthetic_linear.yaml`
- Modify: `apps/backend/brain/cli.py`, `Makefile`, `docs/adding-a-company.md`
- Test: `apps/backend/tests/test_linear_seed.py` (create)

**Interfaces:**
- Consumes: `LinearClient`, `write_json` / `read_json`, Task 7's `tickets/` folder and base `work_items.jsonl`, `CompanyConfig.people.aliases`.
- Produces:
  - `SeedData`, a dataclass with:
    - `tickets: list[WorkItem]`
    - `blocks: list[tuple[str, str]]` (keys)
    - `attachments: list[tuple[str, str, str]]` (key, url, title)
    - `teams: dict[str, str]`
  - `load_seed(tickets_dir: Path) -> SeedData`. Attachment url and title come from the base work item that a MENTIONS link points to.
  - `SeedReport(created: int, skipped: int)`
  - `seed(client: PagedClient, company: CompanyConfig, source: LinearSource, data: SeedData, state_path: Path, log=print) -> SeedReport`
  - The state file `data/raw/<slug>/linear/<workspace>/seed_state.json` holds `{"issues": {key: linear_id}, "relations": ["IDN-1>IDN-2"], "attachments": ["PAY-3 <url>"]}`. It is written atomically after **each** mutation.
  - CLI: `brain linear-seed SLUG [--tickets PATH] [--yes]`. `--tickets` defaults to `apps/backend/examples/synthetic_company/tickets`. Without `--yes`, it prints the target workspace and the counts, and exits 0 without writing.
  - Make: `linear-seed: ## Fill the Linear workspace of $(SLUG) with the synthetic tickets (CONFIRM=1)`

**Order and guards in `seed`:**
1. Refuse unless `company.data_permission == "synthetic"` (`PermissionError`).
2. Run `seed_lookup` (org urlKey; teams with `id key states { id type position }`; users `id displayName active`). Refuse a workspace mismatch.
3. Check, **before any write**:
   - every team key in `data.teams` exists;
   - every assignee login maps to an active user, by `displayName`, after reversing `people.aliases`.

   Report everything missing in one `LinearError`. Missing teams are listed as "create team IDN (Identity)".
4. Map `status_category` to the team's state with that type and the lowest `position`: backlog→backlog, todo→unstarted, in_progress→started, done→completed, canceled→canceled.
5. Create each ticket that is not in the state file with `issueCreate`, passing `teamId, title, description, assigneeId, stateId, priority` (urgent 1 … low 4, None 0), `dueDate` and `createdAt`.
6. Create each relation that is not in the state file with `issueRelationCreate {issueId: blocker, relatedIssueId: blocked, type: blocks}`.
7. Create each attachment that is not in the state file with `attachmentCreate {issueId, url, title}`.

`companies/synthetic_linear.yaml`:
- `slug: synthetic_linear`, `name: Synthetic Co (Linear)`, `data_permission: synthetic`, window `2026-01-01`
- sources:
  1. `canonical_jsonl` at `apps/backend/examples/synthetic_company` (base only, **no** tickets folder, so tickets aren't doubled)
  2. `linear` with `workspace: synthetic-co`, `teams: [IDN, PAY]`
- `systems` and `people` copied from `synthetic.yaml`
- A comment says to set `workspace` to your own workspace's URL key.

- [ ] **Step 1: Write the failing tests** (a FakeClient that records mutations and returns ids):
  - `test_load_seed_counts`: 10 tickets, 4 blocks, 4 attachments; the PAY-3 attachment url is `https://example.com/synthetic/app/pull/9`.
  - `test_refuses_non_synthetic_company`
  - `test_refuses_other_workspace`
  - `test_missing_team_or_user_reported_before_any_write`: no mutation was recorded, and the error names both the team and the user.
  - `test_creates_issues_relations_attachments`: 10 + 4 + 4 mutations. PAY-3 is created with the `started` state id, priority 3 and dueDate `2026-10-30`.
  - `test_rerun_creates_nothing`
  - `test_resumes_after_failure`: the 3rd `issueCreate` raises. The state file holds 2 issues; a rerun creates the other 8, plus the relations and attachments.
  - `test_cli_without_yes_writes_nothing`: typer `CliRunner`, with `seed` monkeypatched to fail if called.
- [ ] **Step 2: Run them, expect failures.**
- [ ] **Step 3: Implement `seed.py`, the four `.graphql` files, the CLI command, the Make target and `synthetic_linear.yaml`.** In `docs/adding-a-company.md`, add:
  - a "(d) Linear" section: YAML, `LINEAR_API_KEY`, the permission rule and aliases;
  - "Synthetic tickets in a real Linear workspace": the Task 10 steps;
  - "Jira (planned)": a short paragraph linking to spec §6.
- [ ] **Step 4: Run the tests, `make test`, `make lint`, and `make brain ARGS="linear-seed synthetic_linear"`.** The last one prints the plan and writes nothing (it errors cleanly when `LINEAR_API_KEY` is unset).
- [ ] **Step 5: Commit:** `git commit -m "Seed a Linear workspace from the synthetic tickets; synthetic_linear company"`.

### Task 10: Live check against a real workspace (run by the user, needs a Linear account)

**Files:** `tests/fixtures/linear/synthetic-co/issues/*.json` (re-recorded), and the spec if the API differs from it.

- [ ] **Step 1: Set up the workspace (user).**
  1. Create a free Linear workspace, and rename `workspace:` in `companies/synthetic_linear.yaml` to its URL key.
  2. Create teams Identity (`IDN`) and Payments (`PAY`).
  3. Invite four accounts you control. Set their display names to `alice`, `bob`, `carol` and `erin`, and add them to the teams from spec §7.
  4. Put a personal API key in `.env` as `LINEAR_API_KEY`.
- [ ] **Step 2: Seed and sync:** `make linear-seed SLUG=synthetic_linear CONFIRM=1`, then `make schema SLUG=synthetic_linear && make sync SLUG=synthetic_linear`. `make stats SLUG=synthetic_linear` shows 10 tickets, 10 ASSIGNED_TO edges, 4 BLOCKS edges, and 4 MENTIONS edges from tickets to PRs/issues that resolved by url.
- [ ] **Step 3: Compare the answers.** `make query SLUG=synthetic_linear TOOL=blocked_on P="login=carol"` gives the same keys, depths and `via` as spec §7. Then run `make ask SLUG=synthetic_linear Q="What is carol waiting on?"`; it cites PAY-3 and PR #9.
- [ ] **Step 4: Re-record the fixture.** Replace the fixture issue pages with trimmed real pages from `data/raw/synthetic_linear/linear/<workspace>/issues/`. Keep the hand-made edge cases (team move, `weird_new_type`, a blocker outside the cache) as a separate page. Rerun `make test`. Fix any field the real API names differently, in the `.graphql` files and in spec §4.
- [ ] **Step 5: Commit:** `git commit -m "Linear fixtures re-recorded from a real workspace"`.
