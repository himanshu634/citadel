# Multi-company frontend (company rail, onboarding, settings) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The SvelteKit app shows every company in a rail and switches with one click, keeps the current section on switch, onboards a new company in four steps with live build progress, and edits a company in Settings with a confirmed rebuild, all reading the backend API.

**Architecture:** Company-scoped routes under `/c/[slug]/`, a typed API client in `src/lib/api/`, and one runes class (`Companies`) in context that holds the company list and live statuses from `GET /api/events`. New components follow `design-system.md` and go in the `/components` gallery. Pure logic (monograms, slugify, section mapping, build-table reduction) lives in `.ts` modules with vitest tests; components are checked with `svelte-check` and in the browser preview.

**Tech Stack:** SvelteKit 2, Svelte 5 runes, TypeScript, bits-ui, Lucide, adapter-static (SPA fallback `200.html`), vitest (new dev dependency, pure modules only).

**Spec:** `docs/superpowers/specs/2026-10-16-multi-company-design.md` (sections 5 and 7) and the canvas linked at its top. **API contract:** `docs/superpowers/plans/2026-10-16-multi-company-backend.md` (Interfaces blocks of Tasks 3–8).

**Base branch:** the same `feat/multi-company` branch, after the backend plan's Task 7 (Tasks 1–3 here can start earlier against the spec's API tables).

## Global Constraints

- Components read tokens only (`src/lib/styles/tokens.css`); no literal colours, sizes or radii.
- One solid accent block per region: the active nav item, the current stepper step, the one primary button. The current company tile is **ink** (ink fill, surface text, weight 900, 4px ink bar on its left edge, `aria-current="true"`), never accent.
- Status is never colour alone: building = spinner icon + warning colour; failed = alert icon + danger colour; plus words in the accessible name.
- Sentence case everywhere; buttons say what happens ("Save and build", "Save and rebuild").
- No ⌘1–9 shortcuts.
- Every new component: `@component` comment, export from `src/lib/index.ts`, shown in `/components` with its states in both themes, `pnpm check` clean, `npx @sveltejs/mcp svelte-autofixer <file>` clean.
- Exact copy from the spec: slug hint "Lowercase letters, digits and underscores, starting with a letter or digit. It cannot change after the first build."; slug errors "Use lowercase letters, digits and underscores only, like acme_labs" and "<slug> is already a company. Pick another name"; date hint "Older activity is skipped. Changing this later rebuilds the graph."; rebuild dialog title "Rebuild <name>'s graph?"; empty first run "Your first company brain will appear here"; building overview "Answers appear when the first build finishes".
- Below 900px rail and sidebar live in the drawer; the page never scrolls sideways.

## Review Focus

1. A slow response for company A lands after the user switched to B: B's page must not show A's data. (Task 2)
2. A company slug in the URL that does not exist (`/c/nope/`): a not-found page with a link to the company list, not a crash or a blank shell. (Task 3)
3. Double-clicking "Save and build" or "Save and rebuild": one request, button shows loading until the response. (Tasks 8, 10)
4. The events stream drops (backend restarted): the rail keeps the last known statuses, reconnects, and refreshes the list on reconnect. (Task 2)
5. Twelve companies, two with the same monogram, one with a 40-character name: the rail scrolls, monograms differ, the tooltip shows the full name. (Tasks 1, 4)

## File Structure

```
apps/frontend/
  package.json, vite.config.ts            modify: vitest, /api proxy to 127.0.0.1:8000
  src/lib/
    types.ts                              modify: Company, CompanyStatus, CompanyConfig, SourceConfig,
                                          BuildEvent, BuildSnapshot, BuildSummary, ConfigDiff,
                                          FieldError, Overview, RecentWorkItem, PersonActivity
    api/client.ts                         create: typed fetch wrappers, ApiError
    api/events.ts                         create: SSE helpers with reconnect
    companies.ts                          create: monogram(), slugify(), sectionPath() (pure)
    build.ts                              create: buildTable() (pure)
    companies.svelte.ts                   create: Companies runes class + context
    components/layout/CompanyRail.svelte  create
    components/layout/AppShell.svelte     modify: rail column, drawer holds rail + sidebar
    components/layout/Sidebar.svelte      modify: company head, company-scoped links, Settings
    components/layout/Topbar.svelte       modify: drop company Menu, company-aware ask + sync line
    components/ui/{Stepper,ChoiceCard,Checkbox,Select,TagInput,Banner}.svelte   create
    components/brain/{ConfigPreview,SourceCard,BuildProgress,CompanyForm}.svelte create
    data/sample.ts                        delete at the end of Task 6
  src/routes/
    +page.svelte                          replace: redirect or first run
    +layout.ts                            modify: prerender stays true at root
    c/[slug]/+layout.ts, +layout.svelte   create: load company, not-found
    c/[slug]/+page.svelte                 create: overview (moved from routes/+page.svelte)
    c/[slug]/build/+page.svelte           create: build progress
    c/[slug]/settings/+page.svelte        create
    new/+page.svelte                      create: onboarding
    components/+page.svelte               modify: gallery entries
  design-system.md                        modify: rail, status badge, stepper
```

---

### Task 1: Types, API client and pure helpers

**Files:**
- Modify: `apps/frontend/package.json` (devDependency `vitest`, script `"test": "vitest run"`), `vite.config.ts` (`server.proxy['/api'] = 'http://127.0.0.1:8000'`, `test.include = ['src/**/*.test.ts']`), `src/lib/types.ts`, `Makefile` (`fe-test`)
- Create: `src/lib/api/client.ts`, `src/lib/companies.ts`, `src/lib/build.ts`
- Test: `src/lib/companies.test.ts`, `src/lib/build.test.ts`

**Interfaces:**
- Produces (types mirror the backend models field for field):
  - `type CompanyStatus = 'ready' | 'building' | 'failed' | 'empty' | 'invalid'`
  - `interface Company { slug; name; data_permission; status: CompanyStatus; last_synced_at: string | null; error: string | null; build: BuildSummary | null }`
  - `api.companies(): Promise<Company[]>`, `api.company(slug)`, `api.validate(draft)`, `api.create(draft)`, `api.update(slug, cfg, opts?: { dryRun?: boolean; rebuild?: boolean })`, `api.startBuild(slug, full = false)`, `api.currentBuild(slug)`, `api.stopBuild(slug)`, `api.overview(slug)`, `api.githubToken()`, `api.githubRepo(owner, name)`. Non-2xx throws `ApiError { status: number; detail: unknown }`.
  - `monogram(names: string[], name: string): string` — spec 5.2 rule: initials of the first two words, else first two letters, title case; on collision with an earlier name (sorted), first letter + the next letter of the name that makes it unique.
  - `slugify(name: string): string` — lowercase, runs of other characters → `_`, trimmed of `_`, must match `^[a-z0-9][a-z0-9_]*$` or return `''`.
  - `sectionPath(pathname: string, toSlug: string): string` — `/c/a/settings` → `/c/b/settings`; `/c/a/build` → `/c/b/`; anything outside `/c/` → `/c/b/`.
  - `buildTable(events: BuildEvent[]): { prepare: Cell; reset?: Cell; rows: { source: string; fetch: Cell; records: Cell; normalize: Cell; load: Cell }[] }` with `Cell = { status: Status; count?: number; message?: string }`; latest event per (source, stage) wins; missing cells are `waiting`.

- [ ] **Step 1: Write the failing tests**

```ts
test('monogram rules', () => {
	const names = ['Acme Labs', 'FalkorDB', 'Foo Corp', 'Fabric'];
	expect(monogram(names, 'Acme Labs')).toBe('AL');
	expect(monogram(names, 'FalkorDB')).toBe('Fa');
	expect(monogram(names, 'Fabric')).not.toBe('Fa');
	expect(monogram(names, 'Foo Corp')).toBe('FC');
});
test('slugify', () => {
	expect(slugify('Acme Labs')).toBe('acme_labs');
	expect(slugify('  --Acme--  ')).toBe('acme');
	expect(slugify('!!!')).toBe('');
});
test('sectionPath keeps the section', () => {
	expect(sectionPath('/c/falkordb/settings', 'synthetic')).toBe('/c/synthetic/settings');
	expect(sectionPath('/c/falkordb/build', 'synthetic')).toBe('/c/synthetic/');
	expect(sectionPath('/new', 'synthetic')).toBe('/c/synthetic/');
});
test('buildTable takes the latest event per cell', () => {
	const t = buildTable([ev('fetch', 'running', 'github:a/b'), ev('fetch', 'done', 'github:a/b', 2310),
		ev('records', 'skipped', 'local_docs:docs', undefined, 'Folder not found')]);
	expect(t.rows[0].fetch).toEqual({ status: 'done', count: 2310 });
	expect(t.rows[0].load.status).toBe('waiting');
	expect(t.rows[1].records.message).toBe('Folder not found');
});
```

- [ ] **Step 2: Run** `make fe-test` — FAIL (modules missing).
- [ ] **Step 3: Implement** the three modules and the types.
- [ ] **Step 4: Run** `make fe-test` and `make fe-check` — pass.
- [ ] **Step 5: Commit** — `git commit -m "Frontend: API types and client, monogram/slug/section helpers, vitest"`

---

### Task 2: Companies state and live statuses

**Files:**
- Create: `src/lib/api/events.ts`, `src/lib/companies.svelte.ts`
- Test: `src/lib/companies.svelte.test.ts` (vitest can run `.svelte.ts` with the Svelte plugin)

**Interfaces:**
- Consumes: Task 1 `api`, `Company`.
- Produces:
  - `openEvents(path: string, handlers: Record<string, (data: unknown) => void>, opts?: { onReconnect?: () => void }): () => void` — `EventSource` with exponential backoff (1s → 30s); returns a close function.
  - `class Companies { list: Company[]; current: string | null; ready: boolean; load(): Promise<void>; byslug(slug): Company | undefined; apply(update: { slug; status; build }): void; guard<T extends { slug: string }>(slug: string, value: T): T | null; start(): () => void }` — `start` loads and subscribes to `/api/events`, reloading the list on reconnect. `guard` returns `null` when `value.slug !== slug` or `slug !== this.current` (Review Focus 1).
  - `setCompanies(c: Companies)`, `getCompanies(): Companies` (context, same pattern as `theme.svelte.ts`).

- [ ] **Step 1: Write the failing tests**

```ts
test('guard drops a response for another company', () => {
	const c = new Companies(); c.current = 'synthetic';
	expect(c.guard('falkordb', { slug: 'falkordb', n: 1 })).toBeNull();
	expect(c.guard('synthetic', { slug: 'synthetic', n: 1 })).toEqual({ slug: 'synthetic', n: 1 });
});
test('apply updates one company status', () => {
	const c = new Companies(); c.list = [co('a', 'ready'), co('b', 'ready')];
	c.apply({ slug: 'b', status: 'building', build: null });
	expect(c.list.map((x) => x.status)).toEqual(['ready', 'building']);
});
```

- [ ] **Step 2–4:** run (fail), implement, run (pass) with `make fe-test`.
- [ ] **Step 5: Commit** — `git commit -m "Frontend: companies state with live statuses and a stale-response guard"`

---

### Task 3: Company-scoped routes

**Files:**
- Create: `src/routes/c/[slug]/+layout.ts`, `+layout.svelte`, `+page.svelte`
- Modify: `src/routes/+page.svelte`, `src/routes/+layout.svelte` (create and provide `Companies`, call `start()` in `onMount`)

**Interfaces:**
- Consumes: Task 2 `getCompanies()`.
- Produces: routes `/` and `/c/[slug]/`. `c/[slug]/+layout.ts`: `export const prerender = false; export const ssr = false;` and `load({ params })` returning `{ slug: params.slug }`. The layout sets `companies.current = slug` and shows a not-found panel ("No company called <slug>", link "See all companies" to `/`) when the list is loaded and the slug is absent. `/`: when the list is loaded, `goto('/c/<last>/')` with `last` from `localStorage['citadel-company']` if it exists in the list, else the first by name; when the list is empty, render the first-run state (Task 6 fills in its content; here a placeholder `EmptyState` with the spec copy). The `/c/[slug]/` layout writes `localStorage['citadel-company']` (wrapped in try/catch).

- [ ] **Step 1: Move** the current overview page body to `c/[slug]/+page.svelte` unchanged (still on `sample.ts`).
- [ ] **Step 2: Implement** the layout, redirect and not-found.
- [ ] **Step 3: Verify** with `make api` + `make fe-dev`: `/` lands on `/c/falkordb/` or `/c/synthetic/`; `/c/nope/` shows the not-found panel; `make fe-build` succeeds (the `[slug]` routes use the `200.html` fallback).
- [ ] **Step 4: Commit** — `git commit -m "Frontend: company-scoped routes, last-company redirect, not-found"`

---

### Task 4: Company rail in the shell

**Files:**
- Create: `src/lib/components/layout/CompanyRail.svelte`
- Modify: `AppShell.svelte`, `src/lib/index.ts`, `src/routes/components/+page.svelte`, `apps/frontend/design-system.md` (sections 3, 6, 7)

**Interfaces:**
- Consumes: Task 1 `monogram`, `sectionPath`; Task 2 `getCompanies()`.
- Produces: `CompanyRail` props `{ companies: Company[]; current: string | null; pathname: string; onnavigate?: () => void }`. Renders a `nav` labelled "Company brains": label "Brains", a `ul` of tiles (`a` with `href={sectionPath(pathname, c.slug)}`, `aria-current="true"` on the current one, accessible name "<name>, graph brain_<slug>[, building | , last build failed | , config invalid]"), a hairline, and the add tile (`href="/new"`, "Add a company"). Tooltip shows name and `brain_<slug>` in mono. Tile list scrolls (`overflow-y: auto`); the add tile stays pinned; the current tile is scrolled into view on mount.

Measurements from the canvas: rail 72px wide, tiles 48×48 at `--radius-md`, gap `--space-2`, monogram 15px at `wdth` 118 weight 700 (900 when current), status badge 20px circle at bottom-right offset 6px with a 12px icon. Add a `--rail-width: 4.5rem` token.

- [ ] **Step 1: Build the component** and the 3-column `AppShell` (`--rail-width` | `--sidebar-width` | main). Under 900px the drawer contains rail + sidebar side by side (canvas board "Below 900px").
- [ ] **Step 2: Gallery** — a "Company rail" card with: 3 companies, current + building + failed + invalid badges, 12 companies (scrolls), a colliding monogram pair, a 40-character name.
- [ ] **Step 3: design-system.md** — section 3: the current company tile is ink (rule from Global Constraints); status badge rule. Section 6: the rail column. Section 7: `CompanyRail` row.
- [ ] **Step 4: Verify** in the preview (`frontend` launch config): one click on a tile changes `/c/<slug>/` and the page; on `/c/a/settings` (after Task 10) a click keeps `settings`; both themes; 375px width shows the drawer with the rail. `make fe-check` clean.
- [ ] **Step 5: Commit** — `git commit -m "Frontend: company rail, one click to switch company"`

---

### Task 5: Sidebar and top bar follow the company

**Files:**
- Modify: `Sidebar.svelte`, `Topbar.svelte`, `AppShell.svelte`

**Interfaces:**
- Consumes: Task 2 `getCompanies()`.
- Produces: Sidebar shows brand, then the company head (name, `brain_<slug>` in mono) when a company is current, nav links built as `/c/<slug>/...`, and a "Company" group with "Settings" (`/c/<slug>/settings`). Top bar: the company `Menu` is removed; ask placeholder "Ask <name> about people, systems or decisions"; when the company is `building` or `empty` the field is disabled with placeholder "Asking opens when <name> finishes building"; the right side shows "Synced <date, time>" from `last_synced_at` (format per design-system.md section 9) or "Building, step <n> of 4" (`n` from `build.stage`: fetch 1, records 2, normalize 3, load 4) or "Last build failed". Under 900px the top bar's menu button shows the current company's monogram tile and opens the drawer.

- [ ] **Step 1: Implement.**
- [ ] **Step 2: Verify** in the preview for a ready, a building and an empty company; `make fe-check`.
- [ ] **Step 3: Commit** — `git commit -m "Frontend: sidebar and top bar follow the current company"`

---

### Task 6: Overview from the API, first run, building and failed states

**Files:**
- Create: `src/lib/components/ui/Banner.svelte`
- Modify: `src/routes/c/[slug]/+page.svelte`, `src/routes/+page.svelte`, `src/lib/index.ts`, gallery
- Delete: `src/lib/data/sample.ts` (move any shape the gallery needs into the gallery page)

**Interfaces:**
- Consumes: `api.overview(slug)`, `Companies.guard`, `Company.status`.
- Produces: `Banner` props `{ tone: 'warning' | 'danger' | 'neutral'; title: string; children?: Snippet; action?: Snippet }`, `role="status"`, icon + words. Overview states (spec 5.4): `ready` → page head + stats + cards mapped from `Overview` (`recent` → `WorkItemRow`, `systems` → `ActivityBars`, `people` → `EntityRow`); the "Latest answer" card is not shown until the ask API exists. `building`/`empty` → warning banner "Building, step <n> of 4" with "See progress" (`/c/<slug>/build`) and `EmptyState` "Answers appear when the first build finishes". `failed` → danger banner with `error` and "See details" above the normal overview. `invalid` → danger banner with the YAML error and no overview. First run on `/`: rail with only the add tile, `h1` "Company brains", `EmptyState` with the spec copy and one primary action "Add a company" plus a sentence naming `make synthetic`. Switching company shows a skeleton until the guarded response for the new slug arrives.

- [ ] **Step 1: Implement** Banner (+ gallery: three tones, long text) and the states.
- [ ] **Step 2: Verify** in the preview: synthetic shows real counts; switch to falkordb and back rapidly — never the other company's numbers (Review Focus 1); stop the API — the page shows an error state, not a blank. `make fe-check`, `make fe-test`.
- [ ] **Step 3: Commit** — `git commit -m "Frontend: overview from the API with building, failed and first-run states"`

---

### Task 7: Form components

**Files:**
- Create: `src/lib/components/ui/Stepper.svelte`, `ChoiceCard.svelte`, `Checkbox.svelte`, `Select.svelte`, `TagInput.svelte`
- Modify: `src/lib/index.ts`, gallery, `design-system.md` section 7

**Interfaces:**
- Produces:
  - `Stepper { steps: { label: string; hint?: string }[]; current: number; done: number[] }` — `ol` with `aria-current="step"`; current step is the solid accent block with square corners; done steps show a check in an ink circle.
  - `ChoiceCard { name: string; value: string; group: string (bindable); title: string; description: string }` — a real radio inside a label; selected = accent border + `--color-accent-soft` fill.
  - `Checkbox { label: string; checked: boolean (bindable); disabled?: boolean }`.
  - `Select { label: string; value: string (bindable); options: { value: string; label: string }[]; hint?: string }` — bits-ui Select.
  - `TagInput { label: string; values: string[] (bindable); placeholder?: string; mono?: boolean }` — Enter or comma adds, each tag has a remove button named "Remove <tag>".

- [ ] **Step 1: Implement** each with default, hover, focus, disabled, error (where it applies) and long-text states in the gallery.
- [ ] **Step 2: Verify** keyboard use for each in the preview (Tab, Space/Enter, arrows in Select and radio groups); both themes; `make fe-check`; autofixer clean.
- [ ] **Step 3: Commit** — `git commit -m "Frontend: stepper, choice card, checkbox, select and tag input"`

---

### Task 8: Onboarding steps 1–3 and the shared company form

**Files:**
- Create: `src/lib/components/brain/CompanyForm.svelte`, `SourceCard.svelte`, `ConfigPreview.svelte`, `src/routes/new/+page.svelte`
- Modify: `src/lib/index.ts`, gallery

**Interfaces:**
- Consumes: Task 7 components; `api.validate`, `api.create`, `api.githubToken`, `api.githubRepo`; `slugify`.
- Produces:
  - `CompanyForm { draft: CompanyConfig (bindable); section: 'company' | 'sources' | 'rules' | 'all'; errors: FieldError[]; slugLocked?: boolean }` — renders the fields of one step (or all for Settings) and puts each `FieldError` under the field whose path matches `loc` (`['sources', 0, 'repo']` → the repo input of source card 0).
  - `SourceCard { source: SourceConfig (bindable); index: number; dataPermission: string; errors: FieldError[]; onremove: () => void }` — GitHub: `github.com/` prefix input, six include checkboxes (labels: Commits, Pull requests, Issues, Reviews, CODEOWNERS, Docs in the repo), token note with "Check again", private-repo error when `dataPermission !== 'own'`; documents folder and JSONL: one path input.
  - `ConfigPreview { yaml: string; highlight: string[] }` — top-level keys in `highlight` are marked; title `companies/<slug>.yaml`; hint "Saved when you start the build."
  - `/new`: Stepper (Company, Sources, Systems and people *Optional*, Build); draft held in page state; every change calls `api.validate` debounced 300ms and feeds `errors` and the preview; "Continue" is disabled while the current step has errors; the slug follows `slugify(name)` until edited; step 3 offers "Skip, use defaults" and primary "Save and build".
  - "Save and build": `api.create(draft)` then `api.startBuild(slug)`, `companies.load()`, `goto('/c/<slug>/build')`. The button shows `loading` and ignores further clicks until the request settles (Review Focus 3). A 409 from create shows the slug-taken error under the slug field and returns to step 1.

- [ ] **Step 1: Implement** the three components and the page; gallery: SourceCard in each type with token-missing and private-repo errors; ConfigPreview with highlights.
- [ ] **Step 2: Verify** in the preview against `make api`: create `acme_labs` with the synthetic JSONL folder as a `canonical_jsonl` source; the YAML preview equals the file written; a bad repo shows its error under the repo field; slug `Acme-Labs` shows the spec error; double-click "Save and build" sends one request (network panel).
- [ ] **Step 3: Commit** — `git commit -m "Frontend: onboarding steps with live validation and config preview"`

---

### Task 9: Build progress

**Files:**
- Create: `src/lib/components/brain/BuildProgress.svelte`, `src/routes/c/[slug]/build/+page.svelte`
- Modify: `src/lib/index.ts`, gallery

**Interfaces:**
- Consumes: `api.currentBuild`, `api.stopBuild`, `openEvents`, `buildTable`.
- Produces: `BuildProgress { snapshot: BuildSnapshot }` — header "Step <n> of 4: <stage>", progress meter, a table (Source | Fetch | Records | Normalize | Load) from `buildTable`, a "Prepare" row (and "Reset" for rebuilds), cells with icon + word + count/message, and the plain log (time, stage, source, count/message per event). The page `/c/[slug]/build` loads the snapshot, subscribes to `/api/companies/<slug>/builds/current/events` (first `snapshot`, then `build` events appended), and shows "Stop build" (ghost) and primary "Go to <name>" (`/c/<slug>/`). When the onboarding flow lands here, the Stepper shows step 4 current. Failed builds show the error and "Retry build"; "Retry rebuild" when `kind === 'rebuild'`.

- [ ] **Step 1: Implement**; gallery: running, done, failed, with a skipped source.
- [ ] **Step 2: Verify** with `make api`: build `synthetic` from the UI and watch the cells move to Done; switch company mid-build and back — the table catches up from the snapshot; restart the API mid-build — the page reconnects and shows "Stopped".
- [ ] **Step 3: Commit** — `git commit -m "Frontend: live build progress page"`

---

### Task 10: Settings with rebuild on save

**Files:**
- Create: `src/routes/c/[slug]/settings/+page.svelte`

**Interfaces:**
- Consumes: Task 8 `CompanyForm` (`section="all"`, `slugLocked`), `Dialog`, `api.update` with `dryRun` / `rebuild`, `api.startBuild`.
- Produces: the page loads `api.company(slug).config` into a draft. "Save" first calls `api.update(slug, draft, { dryRun: true })`:
  - `changed === false` → nothing to save (button stays disabled while the draft equals the loaded config).
  - `rebuild === false` → `api.update(slug, draft)`; toast-free inline "Saved" line next to the button; if `refetch` is non-empty the server started a build and the page links to it.
  - `rebuild === true` → `Dialog` titled "Rebuild <name>'s graph?", body: the `reasons` as a list, "The graph is emptied and rebuilt from the cached data. Answers are unavailable until it finishes.", plus "These sources are downloaded again: <keys>" when `refetch` is non-empty. Actions "Cancel", then primary "Save and rebuild" → `api.update(slug, draft, { rebuild: true })` → `goto('/c/<slug>/build')`.
  - 409 because a build is running → inline error "A build is running. Wait for it or stop it, then save again." with a link to the build page.
  - "Sync now" (secondary) → `api.startBuild(slug)`.

- [ ] **Step 1: Implement.**
- [ ] **Step 2: Verify** with `make api` on a copy company: change the name → saves without dialog; change a path rule → dialog lists the reason, "Save and rebuild" runs reset → load and the overview refills; move the date earlier → dialog names the refetched source; save during a running build → the inline error. Double-click "Save and rebuild" → one request.
- [ ] **Step 3: `make fe-check`, `make fe-test`, `make fe-build`** all pass.
- [ ] **Step 4: Commit** — `git commit -m "Frontend: company settings with confirmed rebuild"`
