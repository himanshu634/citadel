# Multi-company Citadel: company rail, onboarding and the API behind them

Status: draft for review, 2026-10-16. Mockups:
[Citadel multi-company canvas](https://claude.ai/artifact/8B99JD4jt1oAzfXkKwwNoa) (direction A
picked).

## 1. Intent

Citadel already keeps one FalkorDB graph per company (`brain_<slug>`), but only the CLI can use
more than one, and only one slug per command. The goal is one running app that holds many
company brains, lets a person add a new one from the UI, and switches between them with a
single click.

What the user asked for, in their words: "design a ui to onboard a company brain and also
dashboard ui to support multi companies and the user should be able to change it from single
click." They then picked direction A, the company rail.

## 2. Goals, non-goals, anti-goals

Goals

- G1. Every company is visible at all times and one click away (desktop width).
- G2. A person adds a company brain from the UI: company details, sources, optional rules,
  then a build they can watch, without touching YAML or the CLI.
- G3. Switching company keeps the section you are in (Overview stays Overview).
- G4. A build runs in the background; you can switch company while it runs, and the rail shows
  which companies are building or failed.
- G5. The CLI keeps working unchanged against the same companies.

Non-goals (this round)

- Login, user accounts, roles or per-organisation access. **Assumption (mine, not confirmed by
  the user): one user, or one trusted team, sees every company.** If that is wrong, auth becomes
  its own design before any of this ships beyond localhost.
- Scheduled syncs. "Sync now" is manual.
- Reordering, pinning or archiving companies in the rail.
- Editing the slug after the first build (the graph name depends on it).
- Deleting a company from the UI (stays `make reset SLUG=x CONFIRM=1`).

Anti-goals (would make this a failure even if it works)

- Any request, query or cache that can return one company's data while another is selected.
- A second company store that disagrees with `companies/*.yaml`.
- A switcher that needs two clicks for the common case, or a second solid-accent block on screen
  (the design system allows one).
- LLM-written Cypher anywhere on the new read paths.

## 3. What already exists (and why tenancy is mostly there)

- `config.graph_name(slug)` validates the slug (`^[a-z0-9][a-z0-9_]*$`) and returns
  `brain_<slug>`; `load_company(slug)` reads `companies/<slug>.yaml` into `CompanyConfig`
  (`extra="forbid"`).
- `db.graph(slug)` selects the graph on every call; `db.run(slug, name, ...)` is the only query
  path. There is no process-wide "current company", so one server process can serve many
  companies safely as long as every handler passes the slug it was given.
- Raw caches are per company: `data/raw/<slug>/<type>/`.
- `pipeline.fetch(slug)` and `pipeline.ingest(slug)` run one company. Ingest goes source by
  source: `adapter.records` → incremental filter → `normalize` → `loader.load` →
  `set_sync_state`. `SourceUnavailable` makes ingest skip a source with a reason.
- `schema.apply_schema(slug)` creates the range, full-text and vector indexes (vector size from
  `EMBEDDING_DIM`). A new graph needs it before the first load.
- Not on `main` yet, on the linear branch stack `feat/github-adapter` →
  `fix/email-scrub-window-cursor` → `feat/named-tools` → `feat/claude-agent`: the GitHub adapter
  (`adapters/github/`, including the private-repo refusal), source models validated through the
  adapter registry (`SourceConfig`, `CompanyConfig._sources_via_registry`), the `window_since`
  cursor (a changed `window.since` resets the cursor), `brain.tools` (`TOOLS`,
  `call(slug, name, **params)`, `queries/tools/*.cypher`) and the agent
  `ask(slug, question, ...)`. All take the slug per call.
- There is no HTTP API yet. The frontend reads `src/lib/data/sample.ts`; its top bar has a
  company dropdown `Menu` (two clicks), which this design replaces.

## 4. Decisions

### 4.1 Taken by the user

- D1. Direction A: a company rail, a 72px column left of the sidebar, one tile per company.
- D2. One click switches company.
- D3. An onboarding UI for adding a company brain.

### 4.2 My calls (marked so they can be challenged)

- C1. **Registry = `companies/*.yaml`.** The API lists, reads and writes these files; there is no
  database table and no registry graph. Creating a company in the UI writes
  `companies/<slug>.yaml`, so the CLI sees it at once (G5).
- C2. **HTTP API with FastAPI** in the backend package (`brain.api`), served by uvicorn, bound to
  `127.0.0.1` by default. FastAPI because the request and response models are already pydantic.
- C3. **Every company-scoped route has the slug in the path**, `/api/companies/{slug}/...`. A
  shared dependency validates it with `SLUG_RE`, checks that `companies/<slug>.yaml` exists
  (404 if not) and hands the handler the slug. Handlers never read a slug from a body, a header
  or a cookie.
- C4. **Builds are in-process background jobs**, one at a time per company, at most two at once
  across companies (they share one GitHub token). Job state lives in memory plus a small JSON
  file per company (`data/jobs/<slug>.json`) so a restart can report the last result.
  A job that was running when the server stopped shows as "Stopped" after a restart.
- C5. **Progress is streamed over Server-Sent Events.** The pipeline gains an optional
  `on_event` callback; the CLI passes none and behaves as today.
- C6. **The frontend routes are company-scoped**: `/c/[slug]/` (overview), `/c/[slug]/settings`,
  and later `/c/[slug]/ask`, `/graph`, ... Onboarding is `/new`. `/` redirects.
- C7. **The active company tile is ink, not accent**: ink fill, surface text, weight 900, a 4px
  ink bar on its left edge, `aria-current="true"`. The accent block stays with the active nav
  item. This is added to `design-system.md`.
- C8. **No ⌘1–9 shortcuts.** Browsers reserve them for tab switching. Keyboard users tab
  through the rail, which is a `nav` landmark.
- C9. **Base: the branch stack in section 3, merged.** This work starts on `main` after
  `feat/github-adapter` … `feat/claude-agent` have landed. If they have not when the build
  starts, branch from the tip of `feat/claude-agent` and rebase onto `main` once they land;
  never stub the GitHub adapter.
- C10. **Overview reads go through `brain.tools`**, like every other read (its docstring makes
  it the only read path for the CLI, the agents and the UI). New overview queries are new
  `TOOLS` entries in `queries/tools/`, so agents can use them too. Proposed names:
  `recent_work_items`, `changes_by_system`, `people_activity` (`graph_stats` exists). Confirm
  the names with the session that owns `brain/tools.py` before adding them.
- C11. **Rewriting an existing YAML keeps its comments and layout**: updates go through a
  round-trip YAML library (ruamel.yaml), changing only the keys that changed. New files are
  written fresh in the field order of the existing files.

## 5. The UI

### 5.1 Frame

`AppShell` becomes three columns: `CompanyRail` (72px) | `Sidebar` (240px) | main. Below 900px
both rail and sidebar move into the existing drawer, rail on the left of it (canvas board
"Below 900px"); the top bar shows the current company's tile, which opens the drawer.

### 5.2 Company rail (`layout/CompanyRail.svelte`)

- Label "Brains" at the top, then one tile per company, a hairline, then the add tile ("+",
  dashed border, links to `/new`).
- Tile: 48×48, radius md, two-letter monogram in wide bold type, ink on surface. Hover:
  sunken fill. Tooltip (bits-ui `Tooltip`): company name and `brain_<slug>` in mono.
  Accessible name: "Acme Labs, graph brain_acme_labs, building".
- Current tile: see C7.
- Status badge (20px circle at the bottom-right of the tile) with an icon, never colour alone:
  building = spinner icon in warning colour; last build failed = alert icon in danger colour;
  ready = no badge.
- Monograms (my call): first letter of the first two words ("Acme Labs" → "AL"), otherwise the
  first two letters, title case ("FalkorDB" → "Fa"). If two companies get the same monogram,
  the later one (by name) uses its first letter plus the next letter of its name that makes it
  unique ("Fa" / "Fo"). Not stored; computed in the client.
- Order: by name. Many companies: the tile list scrolls inside the rail, the add tile stays
  pinned at the bottom, and the current tile is scrolled into view on load.
- Click: navigate to the same section under the new slug (`/c/fa/settings` → `/c/sy/settings`).
  If the section does not exist for that company yet, go to its overview.

### 5.3 Sidebar and top bar

- Sidebar: brand, then a company head (name, `brain_<slug>` in mono), then the nav groups as
  today, plus a "Company" group with "Settings".
- Top bar: drop the company `Menu`. The ask field's placeholder names the company ("Ask Acme
  Labs about people, systems or decisions"); while the company is still building, the field is
  disabled and says why. The right side shows "Synced today 09:12" or "Building, step 2 of 4".

### 5.4 Overview for one company (`/c/[slug]/`)

The existing dashboard, with its data from the API instead of `sample.ts` and headed by the
company (page title, graph name, "Sync now", "Open graph"). States:

- Ready: as today.
- Building and the graph is empty: a status banner (Building badge, current stage, "See
  progress" link) and an `EmptyState` ("Answers appear when the first build finishes").
- Ready but a later build failed: the normal overview plus a danger banner with the error and
  "See details".

### 5.5 First run (`/` with no companies)

Rail with only the add tile. Page title "Company brains", an `EmptyState` "Your first company
brain will appear here", one primary action "Add a company", and a sentence pointing at
`make synthetic` for demo data.

### 5.6 Onboarding (`/new`)

A stepper (`ui/Stepper`), a form on the left and, on the right, a live preview of the
`companies/<slug>.yaml` the server will write (`brain/ConfigPreview`), with the lines the
current step adds highlighted. The preview text comes from the validate endpoint (6.2), so it
is exactly what will be saved. Nothing is written until the last step.

Step 1, Company → `slug`, `name`, `data_permission`, `window.since`

- Company name (required).
- Graph name: `brain_` prefix plus an input for the slug. Filled from the name (lowercase, runs
  of other characters → `_`, trimmed) until the person edits it. Hint: "Lowercase letters,
  digits and underscores, starting with a letter or digit. It cannot change after the first
  build." Errors: invalid pattern ("Use lowercase letters, digits and underscores only, like
  acme_labs"), already used ("acme_labs is already a company. Pick another name").
- Data permission: three radio cards, Public / Own / Synthetic, with one-line explanations.
- Read activity since: a date. Hint says changing it later rebuilds the graph from the start
  (existing pipeline behaviour).

Step 2, Sources → `sources`

- One card per source, added with "Add a source: GitHub repository / Documents folder / JSONL
  records". At least one source is required.
- GitHub (`type: github`): repository as `owner/name` (with a `github.com/` prefix shown),
  checkboxes for `commits`, `pull_requests`, `issues`, `reviews`, `codeowners`, `repo_docs`
  (all on by default). A token check runs when the card appears: no token → warning note naming
  `GITHUB_TOKEN` and `gh auth token`, with "Check again". A private repository with
  `data_permission` other than `own` gets an inline error, because fetch refuses it.
- Documents folder (`type: local_docs`) and JSONL records (`type: canonical_jsonl`): a path
  relative to the Citadel folder. A missing folder is a warning, not an error: the build skips
  that source.

Step 3, Systems and people (optional) → `systems`, `people`

- Path rules table (glob → system, first match wins), "Files no rule matches" select
  (`depth_1`, `depth_2`, `depth_3`, `none`, default `depth_2`), ignore globs as tags.
- Bots as tags; "Name to login" table for `aliases`.
- Actions: "Skip, use defaults" and the primary "Save and build".

Step 4, Build

- "Save and build" creates the company (6.2) and starts a build (6.3). The new company appears
  in the rail at once with the building badge, and becomes current.
- A progress table, one row per source, one column per stage: Fetch, Records, Normalize, Load,
  each Waiting / Running / Done (with a count) / Skipped (with the reason) / Failed (with the
  error). A "Prepare" row before them covers schema creation. A plain log underneath.
- "Stop build" and the primary "Go to <company>" (the overview, in its building state).

The same progress view is reachable later from the building banner and from Settings.

### 5.7 Settings (`/c/[slug]/settings`)

Steps 1–3 as one page for an existing company, saved with "Save", with the slug read-only.
"Sync now" from here or the overview starts a build with the current config. My call: this is
in scope because the onboarding forms make it nearly free; drop it if the build plan needs to
shrink.

## 6. The API

All JSON. Errors use FastAPI's 422 shape for validation, with `loc` paths that match
`CompanyConfig` fields so the form can put each error under its field. `CompanyConfig` checks
all sources inside one field validator, so its own errors would collapse to `loc: ["sources"]`.
The validate and create endpoints therefore validate each `sources[i]` entry against its
adapter's `source_model` themselves and report `["sources", i, <field>]`.

### 6.1 Companies

| Method and path | Does |
| --- | --- |
| `GET /api/companies` | List from `companies/*.yaml`: `slug`, `name`, `data_permission`, `status` (`ready`, `building`, `failed`, `empty`), `last_synced_at`, `build` summary if one is running. |
| `GET /api/companies/{slug}` | The full config plus status. |
| `PUT /api/companies/{slug}` | Replace the config (Settings). Slug must match the path. Rewrites the YAML. |

`status` comes from: a running job → `building`; last job failed → `failed`; graph missing or
no `SyncState` nodes → `empty`; otherwise `ready`. `last_synced_at` is the latest `SyncState`
update.

### 6.2 Create and validate

| Method and path | Does |
| --- | --- |
| `POST /api/companies/validate` | Body: a draft config. Returns `{ok, errors, yaml}`. `yaml` is the text that would be written. Also reports `slug_taken`. Writes nothing. |
| `POST /api/companies` | Validate, refuse if `companies/<slug>.yaml` exists (409), write it, return the company. |
| `GET /api/checks/github` | `{token: "env" \| "gh" \| null}`. |
| `GET /api/checks/github/{owner}/{name}` | `{exists, private}` for the repository, so step 2 can warn early. |

YAML is written by the server from the validated model, keeping the field order of the existing
files (`slug, name, data_permission, window, sources, systems, people`). Writes are atomic
(temp file, then rename).

### 6.3 Builds

| Method and path | Does |
| --- | --- |
| `POST /api/companies/{slug}/builds` | Start a build: `schema.apply_schema`, then `pipeline.fetch`, then `pipeline.ingest`. Body `{full: bool}`. 409 if one is running for this slug; queued if two are running elsewhere. |
| `GET /api/companies/{slug}/builds/current` | The current or last build: stages per source, counts, errors, start and end times. |
| `GET /api/companies/{slug}/builds/current/events` | SSE stream of build events (below). Sends the current snapshot first. |
| `DELETE /api/companies/{slug}/builds/current` | Ask the build to stop at the next safe point (between sources or batches). |
| `GET /api/events` | One SSE stream of status changes for all companies, for the rail badges. |

Build event: `{slug, stage, source, status, count, message, at}` where `stage` is one of
`prepare`, `fetch`, `records`, `normalize`, `load`, `done`, and `status` one of `waiting`,
`running`, `done`, `skipped`, `failed`, `stopped`. The final event carries the `LoadReport`
totals, including dangling links dropped.

Pipeline change: `fetch`, `ingest` and `apply_schema` take an optional
`on_event: Callable[[BuildEvent], None]`; the adapters may call it for counts while fetching
(GitHub reports pages). No behaviour change when it is `None`.

### 6.4 Reading a company

| Method and path | Does |
| --- | --- |
| `GET /api/companies/{slug}/overview` | Counts per node type, recent work items, changes per system, people with PR and review counts, and the date window. |
| `GET /api/companies/{slug}/tools` and `POST /api/companies/{slug}/tools/{name}` | Thin wrappers over `brain.tools.call(slug, name, **params)` once `feat/named-tools` is on `main`. |
| `POST /api/companies/{slug}/ask` | Wraps `agents.ask(slug, question, ...)` once `feat/claude-agent` is on `main`. Out of this round's build plan except as a stub. |

The overview reads through `brain.tools` (C10): `graph_stats` for counts, and the new
`recent_work_items`, `changes_by_system` and `people_activity` tools.

### 6.5 Isolation rules (tested)

- Every company route resolves the slug once, in the shared dependency, and passes it to
  `db.run` / `tools.call` / `pipeline.*`. No module-level "current slug".
- Responses carry the slug they were built for; the frontend ignores a response whose slug is
  not the current one (protects against a slow response landing after a switch).
- Client caches are keyed by slug; switching never shows the previous company's data, even for
  a frame (show a skeleton instead).

## 7. Frontend structure

- `src/lib/api/` — typed client (`fetch` wrappers, SSE helpers), shapes in `src/lib/types.ts`
  (add `Company`, `CompanyStatus`, `CompanyConfig`, `BuildEvent`, `BuildSnapshot`).
- `src/lib/companies.svelte.ts` — a runes class in context: the company list, the current slug
  (from the route), status updates from `GET /api/events`.
- Routes: `/` (redirect to the last used company from `localStorage`, else the first by name,
  else first run), `/c/[slug]/+layout` (loads the company, 404 page if unknown),
  `/c/[slug]/+page` (overview), `/c/[slug]/settings`, `/new`. `[slug]` routes are not
  prerendered (`export const prerender = false`) and use the existing `200.html` fallback.
- New components, each in the `/components` gallery with its states and in both themes:
  `layout/CompanyRail`, `ui/Stepper`, `ui/ChoiceCard` (radio card), `ui/TagInput`,
  `ui/Checkbox`, `ui/Select` (bits-ui), `brain/ConfigPreview`, `brain/BuildProgress`,
  `brain/SourceCard`, `ui/Banner`.
- `design-system.md`: add the rail (C7), the status badge rule and the stepper (the current
  step is the solid accent block, like a selected tab).
- Dev: the Vite dev server proxies `/api` to the backend; `make api` runs uvicorn; `make dev`
  runs both.

## 8. Testing

- Backend: API tests against a temporary `BRAIN_ROOT` with its own `companies/`; create →
  validate errors → 409 on duplicate; YAML round-trip equals `load_company`; build job with the
  synthetic company end to end (needs `make up`); SSE event order; stop. An isolation test
  loads two companies and checks that every company route returns only its own uids.
- Frontend: `pnpm check`; gallery states; the rail at 1, 3 and 12 companies, a colliding
  monogram, a long name, and the drawer under 900px; both themes.

## 9. Left to the builder

- Exact SSE reconnect and backoff behaviour.
- How fetch reports counts per adapter (GitHub pages, document files).
- Layout details not fixed by the canvas, within `design-system.md`.
- Whether `/new` keeps step state in the URL or in memory (losing a half-filled form on reload
  is acceptable).

## 10. Suggested build order

1. API skeleton: companies list/get/validate/create, slug dependency, isolation test.
2. Build jobs: pipeline `on_event`, job runner, build endpoints, SSE.
3. Frontend frame: API client, companies store, `/c/[slug]` routes, `CompanyRail`, top bar and
   sidebar changes, first run.
4. Onboarding `/new` and its components.
5. Overview from the API (after the tool queries are agreed), building and failed states.
6. Settings page.
