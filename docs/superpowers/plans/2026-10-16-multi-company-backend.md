# Multi-company backend (API, builds, overview) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An HTTP API that lists, creates, validates and edits companies from `companies/*.yaml`, runs builds and rebuilds as background jobs with streamed progress, and serves a per-company overview, with every company route scoped by the slug in its path.

**Architecture:** A FastAPI app in `brain.api` over three new pure-ish modules: `brain.registry` (company YAML files: list, read, validate, write, round-trip update), `brain.config_diff` (what a config change requires) and `brain.jobs` (one background build per company, at most two at once, events fanned out to SSE subscribers). The existing pipeline and schema gain an optional `on_event` callback; the CLI passes none. Overview reads go through `brain.tools`.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, sse-starlette, ruamel.yaml, pydantic 2, FalkorDB, pytest (FastAPI `TestClient`).

**Spec:** `docs/superpowers/specs/2026-10-16-multi-company-design.md` (read sections 4–6 and 8 before starting).

**Base branch:** `feat/multi-company`, cut from `main` if `feat/github-adapter` … `feat/claude-agent` have merged, else from `origin/feat/claude-agent` and rebased onto `main` once they land (spec C9). Work in its own git worktree: other sessions share the main checkout.

## Global Constraints

- Slug pattern `^[a-z0-9][a-z0-9_]*$` (`config.SLUG_RE`); graph name `brain_<slug>` via `config.graph_name`.
- Every company route is `/api/companies/{slug}/...`; the slug is resolved once by `api.deps.company_slug` and never read from a body, header or cookie.
- Python never holds Cypher strings: new queries are files under `apps/backend/queries/<folder>/<name>.cypher` with the `//` header (purpose / params / returns).
- Overview reads go through `brain.tools.call(slug, name, **params)`; no LLM-written Cypher.
- Server binds `127.0.0.1` by default. No auth this round.
- At most one build per company and at most two builds at once across companies.
- Build stages, in order: `reset` (rebuilds only), `prepare`, `fetch`, `records`, `normalize`, `load`, `done`. Statuses: `waiting`, `running`, `done`, `skipped`, `failed`, `stopped`.
- Company status values: `ready`, `building`, `failed`, `empty`, `invalid`.
- YAML field order for new files: `slug, name, data_permission, window, sources, systems, people`. Updates keep comments and layout (ruamel round-trip). Writes are atomic (temp file + rename).
- Ruff: line length 100, py312. Tests in `apps/backend/tests/`; graph tests use `needs_graph` / `synthetic_graph` from `conftest.py` and only touch `brain_test_*` graphs.

## Review Focus

1. A company YAML on disk that no longer validates (hand edit) must not break `GET /api/companies`: that company is listed with status `invalid` and its error; the others list normally. (Tasks 1 and 3)
2. A slug that is not a valid slug (`Acme-Labs`, `..`, `a/b`) never reaches the filesystem or FalkorDB: 404 before any file or graph access. (Task 3)
3. Double-submitting "Save and build" or "Sync now" for the same company: the second request gets 409 and no second job starts. (Task 7)
4. The server stops mid-build: after restart the company's last build reads `stopped`, not `running`, and a new build can start. (Task 6)
5. A rebuild that fails after `reset`: YAML keeps the new config, status is `failed`, and starting a build again works. (Task 6)

## File Structure

```
apps/backend/
  pyproject.toml                      modify: add fastapi, uvicorn[standard], sse-starlette, ruamel.yaml
  brain/
    events.py                         create: BuildEvent, Stage, Status, BuildStopped
    registry.py                       create: company YAML files (list/read/validate/render/write/update)
    config_diff.py                    create: ConfigDiff, diff(old, new)
    jobs.py                           create: JobRunner, BuildSnapshot, JobRunning
    pipeline.py                       modify: on_event + keys filter
    schema.py                         modify: on_event
    tools.py                          modify: recent_work_items, people_activity tools
    api/
      __init__.py                     create: create_app(), app
      deps.py                         create: company_slug, get_runner
      models.py                       create: response/request models
      companies.py                    create: list/get/validate/create/put routes
      checks.py                       create: GitHub token + repo checks
      builds.py                       create: build routes + SSE
      overview.py                     create: GET overview
  queries/
    load/sync_state_latest.cypher     create
    tools/recent_work_items.cypher    create
    tools/people_activity.cypher      create
  tests/
    api/conftest.py                   create: api_root fixture, client fixture
    test_registry.py, test_config_diff.py, test_jobs.py, test_pipeline_events.py
    api/test_companies.py, api/test_builds.py, api/test_overview.py
Makefile                              modify: api, dev targets
```

---

### Task 1: Company registry (YAML files)

**Files:**
- Create: `apps/backend/brain/registry.py`
- Modify: `apps/backend/pyproject.toml` (add `ruamel.yaml>=0.18`)
- Test: `apps/backend/tests/test_registry.py`

**Interfaces:**
- Consumes: `config.CompanyConfig`, `config.companies_dir()`, `config.SLUG_RE`, `adapters.REGISTRY[type].source_model`.
- Produces:
  - `FieldError(BaseModel)`: `loc: list[str | int]`, `msg: str`
  - `InvalidCompany(BaseModel)`: `slug: str`, `error: str`
  - `list_companies() -> list[CompanyConfig | InvalidCompany]` — every `companies/*.yaml`, sorted by `name` (invalid ones by slug, after valid ones).
  - `exists(slug: str) -> bool`
  - `read(slug: str) -> CompanyConfig` (wraps `config.load_company`)
  - `validate_draft(data: dict) -> tuple[CompanyConfig | None, list[FieldError]]`
  - `render_yaml(cfg: CompanyConfig) -> str`
  - `write_new(cfg: CompanyConfig) -> Path` — raises `FileExistsError` if the file exists.
  - `update(slug: str, cfg: CompanyConfig) -> None` — round-trip edit of the existing file.

- [ ] **Step 1: Write the failing tests** (use `monkeypatch.setattr(config, "REPO_ROOT", tmp_path)` and create `tmp_path / "companies"`)

```python
def test_render_then_load_round_trips(tmp_root):
    cfg = synthetic_company("acme_labs")
    registry.write_new(cfg)
    assert config.load_company("acme_labs") == cfg
    text = (tmp_root / "companies" / "acme_labs.yaml").read_text()
    keys = [l.split(":")[0] for l in text.splitlines() if l and not l.startswith(" ")]
    assert keys == ["slug", "name", "data_permission", "window", "sources", "systems", "people"]

def test_write_new_refuses_existing(tmp_root):
    registry.write_new(synthetic_company("acme_labs"))
    with pytest.raises(FileExistsError):
        registry.write_new(synthetic_company("acme_labs"))

def test_update_keeps_comments(tmp_root):
    shutil.copy(REPO / "companies" / "falkordb.yaml", tmp_root / "companies" / "falkordb.yaml")
    cfg = registry.read("falkordb")
    registry.update("falkordb", cfg.model_copy(update={"name": "FalkorDB Inc"}))
    text = (tmp_root / "companies" / "falkordb.yaml").read_text()
    assert "# how file paths map to System nodes" in text
    assert "name: FalkorDB Inc" in text
    assert registry.read("falkordb").name == "FalkorDB Inc"

def test_validate_draft_reports_source_field_paths():
    draft = {"slug": "acme_labs", "name": "Acme", "data_permission": "own",
             "window": {"since": "2026-04-15"},
             "sources": [{"type": "github", "repo": "not a repo"}]}
    cfg, errors = registry.validate_draft(draft)
    assert cfg is None
    assert [e.loc for e in errors] == [["sources", 0, "repo"]]

def test_validate_draft_slug_error_path():
    _, errors = registry.validate_draft({**VALID_DRAFT, "slug": "Acme-Labs"})
    assert ["slug"] in [e.loc for e in errors]

def test_list_companies_keeps_going_past_a_broken_file(tmp_root):
    registry.write_new(synthetic_company("acme_labs"))
    (tmp_root / "companies" / "broken.yaml").write_text("slug: broken\nname: [\n")
    out = registry.list_companies()
    assert [getattr(c, "slug") for c in out] == ["acme_labs", "broken"]
    assert isinstance(out[1], registry.InvalidCompany)
```

`synthetic_company` comes from `tests/conftest.py`; put the `tmp_root` fixture and `VALID_DRAFT` in the test module.

- [ ] **Step 2: Run them to see them fail**

Run: `make test ARGS="apps/backend/tests/test_registry.py -v"`
Expected: FAIL, `ModuleNotFoundError: No module named 'brain.registry'`.

- [ ] **Step 3: Implement `brain/registry.py`**

`validate_draft` validates `sources[i]` one by one against `REGISTRY[type].source_model` and prefixes each error's `loc` with `["sources", i]`; then validates the rest with `CompanyConfig.model_validate` and keeps only errors whose `loc` does not start with `sources`. `render_yaml` dumps `cfg.model_dump(mode="json", exclude_defaults=False)` in the field order above with ruamel (`default_flow_style=False`). `update` loads the file with ruamel round-trip, assigns changed top-level keys (and nested keys inside `window`, `systems`, `people`; replaces `sources` as a whole), dumps to a temp file in the same folder, `os.replace`. Module docstring follows the house "Why:" style.

- [ ] **Step 4: Run the tests to see them pass**

Run: `make test ARGS="apps/backend/tests/test_registry.py -v"`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/brain/registry.py apps/backend/tests/test_registry.py apps/backend/pyproject.toml uv.lock
git commit -m "Add company registry: list, validate, write and round-trip update company YAML"
```

---

### Task 2: What a config change requires

**Files:**
- Create: `apps/backend/brain/config_diff.py`
- Test: `apps/backend/tests/test_config_diff.py`

**Interfaces:**
- Produces:
  - `ConfigDiff(BaseModel)`: `rebuild: bool`, `refetch: list[str]` (adapter keys, e.g. `github:acme-labs/platform`), `reasons: list[str]`, `changed: bool`
  - `diff(old: CompanyConfig, new: CompanyConfig) -> ConfigDiff`

Rules (spec 5.7): rebuild if `window.since` changed, a source was removed or changed, or `systems` / `people` changed. `name`, `data_permission` and added sources do not rebuild. `refetch` = keys of added sources, changed sources, and, when `since` moved earlier, every source. Reasons are plain sentences shown in the dialog.

- [ ] **Step 1: Write the failing tests**

```python
def test_name_change_needs_nothing():
    d = diff(BASE, BASE.model_copy(update={"name": "Other"}))
    assert (d.changed, d.rebuild, d.refetch) == (True, False, [])

def test_added_source_fetches_without_rebuild():
    d = diff(BASE, with_sources(BASE, BASE.sources + [DOCS]))
    assert (d.rebuild, d.refetch) == (False, ["local_docs:data/inbox/acme_labs/docs"])

def test_removed_source_rebuilds_from_cache():
    d = diff(with_sources(BASE, BASE.sources + [DOCS]), BASE)
    assert (d.rebuild, d.refetch) == (True, [])

def test_rules_change_rebuilds_from_cache():
    d = diff(BASE, with_rules(BASE, [{"match": "src/**", "system": "Core"}]))
    assert (d.rebuild, d.refetch) == (True, [])

def test_since_earlier_refetches_everything():
    d = diff(BASE, with_since(BASE, "2026-01-01"))
    assert d.rebuild and d.refetch == ["github:acme-labs/platform"]

def test_since_later_rebuilds_from_cache():
    d = diff(BASE, with_since(BASE, "2026-06-01"))
    assert (d.rebuild, d.refetch) == (True, [])

def test_changed_include_refetches_that_source():
    d = diff(BASE, with_sources(BASE, [GITHUB.model_copy(update={"include": ["commits"]})]))
    assert d.rebuild and d.refetch == ["github:acme-labs/platform"]
```

`BASE` is an `acme_labs` config with one github source `GITHUB` (`acme-labs/platform`); `DOCS` is a `local_docs` source at `data/inbox/acme_labs/docs`. Helpers build modified copies.

- [ ] **Step 2: Run to see them fail** — `make test ARGS="apps/backend/tests/test_config_diff.py -v"`, expect ImportError.
- [ ] **Step 3: Implement `diff`** — compare sources by adapter key (`REGISTRY[s.type].key(s)`), a source "changed" when its key matches but its `model_dump()` differs.
- [ ] **Step 4: Run to see them pass** — expect 7 passed.
- [ ] **Step 5: Commit** — `git commit -m "Add config diff: which config changes rebuild or refetch"`

---

### Task 3: API skeleton, slug dependency, company reads

**Files:**
- Create: `apps/backend/brain/api/__init__.py`, `deps.py`, `models.py`, `companies.py`
- Create: `apps/backend/queries/load/sync_state_latest.cypher`
- Modify: `apps/backend/pyproject.toml` (add `fastapi>=0.115`, `uvicorn[standard]>=0.30`, `sse-starlette>=2.1`)
- Test: `apps/backend/tests/api/conftest.py`, `apps/backend/tests/api/test_companies.py`

**Interfaces:**
- Consumes: Task 1 `registry.*`; `db.graph_exists(slug)`; `db.run`.
- Produces:
  - `create_app() -> FastAPI`; module-level `app = create_app()`. Routers mounted under `/api`. (Task 7 changes it to `create_app(runner: JobRunner | None = None)`.)
  - `deps.company_slug(slug: str) -> str` — 404 `{"detail": "No company <slug>"}` if the slug fails `SLUG_RE` or `registry.exists` is false.
  - `models.CompanyOut`: `slug, name, data_permission, status, last_synced_at: str | None, error: str | None, build: BuildSummary | None` (`BuildSummary` is defined in Task 6; use `None` here).
  - `models.CompanyDetail(CompanyOut)`: `config: dict`
  - `api.companies.status_of(slug: str) -> tuple[Status, str | None]` — `empty` if the graph is missing or has no `SyncState`, else `ready` (Task 7 adds `building`/`failed` from the runner).
  - Query `load/sync_state_latest`: returns `last_synced_at` (max `SyncState.synced_at`) and `sources` count. Check the property name `set_sync_state` writes before naming it.
- Routes: `GET /api/companies` → `list[CompanyOut]`; `GET /api/companies/{slug}` → `CompanyDetail`.

- [ ] **Step 1: Write the failing tests** (`api_root` fixture = Task 1's `tmp_root`; `client` = `TestClient(create_app())`; monkeypatch `status_of` to avoid FalkorDB in unit tests)

```python
def test_list_is_sorted_by_name_and_includes_invalid(client, api_root):
    write(api_root, "zeta", name="Zeta"); write(api_root, "acme_labs", name="Acme Labs")
    (api_root / "companies" / "broken.yaml").write_text("slug: [\n")
    body = client.get("/api/companies").json()
    assert [c["slug"] for c in body] == ["acme_labs", "zeta", "broken"]
    assert body[2]["status"] == "invalid" and body[2]["error"]

@pytest.mark.parametrize("slug", ["Acme-Labs", "nope", "..", "a%2Fb"])
def test_unknown_or_bad_slug_is_404(client, api_root, slug):
    assert client.get(f"/api/companies/{slug}").status_code == 404

def test_get_returns_config(client, api_root):
    write(api_root, "acme_labs", name="Acme Labs")
    body = client.get("/api/companies/acme_labs").json()
    assert body["config"]["slug"] == "acme_labs" and body["status"] in {"ready", "empty"}

@needs_graph
def test_status_from_graph(api_root, synthetic_graph):
    write(api_root, synthetic_graph, name="Test")
    assert status_of(synthetic_graph)[0] == "ready"
    assert status_of("test_never_built")[0] == "empty"
```

- [ ] **Step 2: Run to see them fail** — `make test ARGS="apps/backend/tests/api -v"`.
- [ ] **Step 3: Implement** the app, `company_slug`, models and the two routes. `create_app` sets CORS for `http://localhost:5173` only.
- [ ] **Step 4: Run to see them pass.**
- [ ] **Step 5: Commit** — `git commit -m "Add the API skeleton with slug-scoped company reads"`

---

### Task 4: Validate, create and GitHub checks

**Files:**
- Modify: `apps/backend/brain/api/companies.py`, `models.py`
- Create: `apps/backend/brain/api/checks.py`
- Test: `apps/backend/tests/api/test_companies.py`, `apps/backend/tests/api/test_checks.py`

**Interfaces:**
- Consumes: `registry.validate_draft`, `registry.render_yaml`, `registry.write_new`, `registry.exists`; `adapters.github.client.token()` (raises `GithubError` when missing).
- Produces:
  - `POST /api/companies/validate` body `dict` → `ValidateOut`: `ok: bool`, `errors: list[FieldError]`, `yaml: str | None`, `slug_taken: bool`.
  - `POST /api/companies` body `dict` → 201 `CompanyDetail`; 422 `{"detail": [FieldError...]}`; 409 `{"detail": "acme_labs is already a company. Pick another name"}`.
  - `GET /api/checks/github` → `{"token": "env" | "gh" | null}`.
  - `GET /api/checks/github/{owner}/{name}` → `{"exists": bool, "private": bool | null}`; uses one GraphQL query file `adapters/github/queries/repo_visibility.graphql` through `GithubClient.query`.

- [ ] **Step 1: Write the failing tests**

```python
def test_validate_returns_yaml_and_writes_nothing(client, api_root):
    r = client.post("/api/companies/validate", json=VALID_DRAFT).json()
    assert r["ok"] and r["yaml"].startswith("slug: acme_labs")
    assert not (api_root / "companies" / "acme_labs.yaml").exists()

def test_validate_reports_slug_taken(client, api_root):
    write(api_root, "acme_labs", name="Acme Labs")
    assert client.post("/api/companies/validate", json=VALID_DRAFT).json()["slug_taken"]

def test_create_writes_file(client, api_root):
    assert client.post("/api/companies", json=VALID_DRAFT).status_code == 201
    assert config.load_company("acme_labs").name == "Acme Labs"

def test_create_twice_is_409(client, api_root):
    client.post("/api/companies", json=VALID_DRAFT)
    r = client.post("/api/companies", json=VALID_DRAFT)
    assert r.status_code == 409 and "already a company" in r.json()["detail"]

def test_create_invalid_is_422_with_field_paths(client, api_root):
    bad = {**VALID_DRAFT, "sources": [{"type": "github", "repo": "x"}]}
    r = client.post("/api/companies", json=bad)
    assert r.status_code == 422 and r.json()["detail"][0]["loc"] == ["sources", 0, "repo"]

def test_token_check_without_token(client, monkeypatch):
    monkeypatch.setattr(checks, "token_source", lambda: None)
    assert client.get("/api/checks/github").json() == {"token": None}
```

- [ ] **Step 2: Run to see them fail.**
- [ ] **Step 3: Implement.** `checks.token_source() -> Literal["env", "gh"] | None` checks `get_settings().github_token` first, then `gh auth token`; never returns or logs the token itself.
- [ ] **Step 4: Run to see them pass.**
- [ ] **Step 5: Commit** — `git commit -m "Add company validate/create routes and GitHub checks"`

---

### Task 5: Build events from the pipeline

**Files:**
- Create: `apps/backend/brain/events.py`
- Modify: `apps/backend/brain/pipeline.py`, `apps/backend/brain/schema.py`
- Test: `apps/backend/tests/test_pipeline_events.py`

**Interfaces:**
- Produces:
  - `Stage = Literal["reset", "prepare", "fetch", "records", "normalize", "load", "done"]`
  - `Status = Literal["waiting", "running", "done", "skipped", "failed", "stopped"]`
  - `@dataclass BuildEvent`: `slug: str`, `stage: Stage`, `status: Status`, `source: str | None = None` (adapter key), `count: int | None = None`, `message: str | None = None`, `at: str` (ISO UTC, default now), `totals: dict | None = None` (final event: `LoadReport.written`, `LoadReport.dropped`)
  - `OnEvent = Callable[[BuildEvent], None]`
  - `class BuildStopped(Exception)` — raised by an `on_event` callback to stop the pipeline.
  - `pipeline.fetch(slug, only=None, keys: set[str] | None = None, on_event: OnEvent | None = None) -> list[str]` — `keys` limits to those adapter keys.
  - `pipeline.ingest(slug, full=False, only=None, on_event: OnEvent | None = None) -> IngestReport`
  - `schema.apply_schema(slug, on_event: OnEvent | None = None) -> SchemaReport`

Events per source: `fetch running` → `fetch done`; `records running` → `records done (count=read)` or `records skipped (message=reason)`; `normalize done (count=loaded)`; `load running` → `load done (count=rows written)`. `prepare running/done` around schema. A source whose adapter raises during fetch emits `fetch failed (message=str(e))` and re-raises.

- [ ] **Step 1: Write the failing tests** (graph-backed, `needs_graph`; company YAML from `synthetic_company("test_events")` written into a tmp `REPO_ROOT`)

```python
@needs_graph
def test_ingest_emits_stages_in_order(events_company):
    seen = []
    pipeline.ingest(events_company, full=True, on_event=seen.append)
    assert [(e.stage, e.status) for e in seen] == [
        ("records", "running"), ("records", "done"), ("normalize", "done"),
        ("load", "running"), ("load", "done")]
    assert seen[1].count > 0 and seen[1].source.startswith("canonical_jsonl:")

@needs_graph
def test_missing_folder_is_skipped(events_company_missing_folder):
    seen = []
    pipeline.ingest(events_company_missing_folder, on_event=seen.append)
    assert seen[-1].stage == "records" and seen[-1].status == "skipped" and seen[-1].message

def test_fetch_keys_filter(monkeypatch, two_source_company):
    fetched = []  # RecordingAdapter.fetch appends adapter.key(source)
    monkeypatch.setitem(adapters.REGISTRY, "local_docs", RecordingAdapter("local_docs", fetched))
    monkeypatch.setitem(adapters.REGISTRY, "canonical_jsonl", RecordingAdapter("canonical_jsonl", fetched))
    pipeline.fetch(two_source_company, keys={"local_docs:docs"})
    assert fetched == ["local_docs:docs"]

@needs_graph
def test_stop_from_callback(events_company):
    def stop(e):
        if e.stage == "load":
            raise BuildStopped
    with pytest.raises(BuildStopped):
        pipeline.ingest(events_company, full=True, on_event=stop)

def test_cli_path_unchanged():
    assert inspect.signature(pipeline.ingest).parameters["on_event"].default is None
```

- [ ] **Step 2: Run to see them fail.**
- [ ] **Step 3: Implement** the events module and the callbacks (a local `emit = on_event or (lambda e: None)`).
- [ ] **Step 4: Run** `make test` (whole suite: existing pipeline tests must still pass).
- [ ] **Step 5: Commit** — `git commit -m "Emit build events from schema, fetch and ingest"`

---

### Task 6: Job runner

**Files:**
- Create: `apps/backend/brain/jobs.py`
- Test: `apps/backend/tests/test_jobs.py`

**Interfaces:**
- Consumes: Task 5 events; `pipeline.fetch/ingest`, `schema.apply_schema`, `db.delete_graph`; `config.REPO_ROOT`.
- Produces:
  - `Kind = Literal["build", "rebuild"]`
  - `BuildSnapshot(BaseModel)`: `slug, kind, state: Literal["queued", "running", "done", "failed", "stopped"], started_at, ended_at: str | None, events: list[BuildEvent]` (stage table is derived client-side), `error: str | None`
  - `BuildSummary(BaseModel)`: `state`, `stage: Stage | None`, `started_at` — used by `CompanyOut.build`
  - `class JobRunning(Exception)`
  - `class JobRunner`:
    - `__init__(self, max_parallel: int = 2, steps: Steps | None = None, jobs_dir: Path | None = None)` — `steps` defaults to the real pipeline; tests inject fakes. `jobs_dir` defaults to `REPO_ROOT / "data" / "jobs"`.
    - `start(slug: str, kind: Kind = "build", full: bool = False, refetch: set[str] | None = None) -> BuildSnapshot` — raises `JobRunning` if this slug has a queued or running job.
    - `stop(slug: str) -> bool`
    - `current(slug: str) -> BuildSnapshot | None` — the running job, else the last one from `data/jobs/<slug>.json`.
    - `subscribe(slug: str | None) -> AsyncIterator[BuildEvent]` — `None` = all companies; first yields nothing historical (the route sends the snapshot).
    - `recover() -> None` — on startup, any persisted `running`/`queued` becomes `stopped`.
  - `Steps` (Protocol): `reset(slug)`, `prepare(slug, on_event)`, `fetch(slug, keys, on_event)`, `ingest(slug, full, on_event)`.

Order: build = `prepare → fetch(keys=None) → ingest(full)`; rebuild = `reset → prepare → fetch(keys=refetch)` (skipped when `refetch` is empty) `→ ingest(full=True)`. Each job runs in a worker thread; a `threading.Semaphore(max_parallel)` queues the third. Stop sets a per-job `threading.Event`; the runner's own `on_event` wrapper raises `BuildStopped` when it is set. Events go to subscribers with `loop.call_soon_threadsafe(queue.put_nowait, event)`. The snapshot file is rewritten (atomically) on every event.

- [ ] **Step 1: Write the failing tests** (fake `Steps` that emit events and can block on a `threading.Event`)

```python
def test_second_start_same_slug_raises(runner, gate):
    runner.start("a"); 
    with pytest.raises(JobRunning):
        runner.start("a")

def test_third_company_queues(runner, gate):
    runner.start("a"); runner.start("b")
    assert runner.start("c").state == "queued"
    gate.set(); wait_done(runner, "c")
    assert runner.current("c").state == "done"

def test_rebuild_order(runner_recording):
    runner_recording.start("a", kind="rebuild", refetch=set()); wait_done(runner_recording, "a")
    assert runner_recording.steps.calls == ["reset", "prepare", "ingest(full=True)"]

def test_stop(runner, gate):
    runner.start("a"); runner.stop("a"); gate.set(); wait_done(runner, "a")
    assert runner.current("a").state == "stopped"

def test_failed_step_records_error(runner_failing):
    runner_failing.start("a"); wait_done(runner_failing, "a")
    snap = runner_failing.current("a")
    assert snap.state == "failed" and "boom" in snap.error

def test_restart_marks_running_as_stopped(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(RUNNING_SNAPSHOT))
    r = JobRunner(jobs_dir=tmp_path, steps=FakeSteps()); r.recover()
    assert r.current("a").state == "stopped"
    r.start("a")  # does not raise

async def test_subscribe_gets_events(runner):
    it = runner.subscribe("a").__aiter__()
    runner.start("a")
    assert (await asyncio.wait_for(it.__anext__(), 2)).stage == "prepare"
```

Also, graph-backed: `test_rebuild_failure_after_reset_leaves_failed_and_retry_works` with real steps on `test_rebuild` (make `ingest` raise once), asserting state `failed`, the graph missing, then a second `start` finishing `done` (Review Focus 5).

- [ ] **Step 2: Run to see them fail.**
- [ ] **Step 3: Implement `brain/jobs.py`.**
- [ ] **Step 4: Run to see them pass** (`pytest-asyncio` is not a dependency: run the async test with `asyncio.run` inside a sync test, or add `anyio`'s pytest plugin, which FastAPI already brings).
- [ ] **Step 5: Commit** — `git commit -m "Add the build job runner: one per company, two at once, stoppable, persisted"`

---

### Task 7: Build routes, SSE, settings save with rebuild

**Files:**
- Create: `apps/backend/brain/api/builds.py`
- Modify: `apps/backend/brain/api/__init__.py` (`create_app(runner: JobRunner | None = None)`; startup calls `runner.recover()`), `deps.py` (`get_runner`), `companies.py` (`status_of` uses the runner; `PUT`)
- Test: `apps/backend/tests/api/test_builds.py`

**Interfaces:**
- Consumes: Task 6 `JobRunner`, Task 2 `config_diff.diff`, Task 1 `registry.update`.
- Produces:
  - `POST /api/companies/{slug}/builds` body `{"full": false}` → 202 `BuildSnapshot`; 409 `{"detail": "A build for acme_labs is already running"}`.
  - `GET /api/companies/{slug}/builds/current` → `BuildSnapshot`; 404 if never built.
  - `GET /api/companies/{slug}/builds/current/events` → SSE: first event `snapshot` (the `BuildSnapshot`), then `build` events (`BuildEvent` JSON).
  - `DELETE /api/companies/{slug}/builds/current` → 202 / 404.
  - `GET /api/events` → SSE `status` events: `{"slug", "status", "build": BuildSummary | null}` whenever a job changes state or stage.
  - `PUT /api/companies/{slug}?dry_run=1` → `ConfigDiff`; `PUT` without flags → 200 `CompanyDetail` when no rebuild is needed, 409 `{"detail": {"rebuild_required": ConfigDiff}}` when it is; `PUT ?rebuild=1` → writes YAML, `runner.start(slug, kind="rebuild", refetch=set(diff.refetch))`, 202 `BuildSnapshot`. A PUT while a build runs → 409. When only sources were added, PUT writes the YAML and starts a normal build with `fetch(keys=refetch)`.
  - `status_of`: running/queued job → `building`; last job `failed` → `failed`; else graph-based.

- [ ] **Step 1: Write the failing tests** (client built with `create_app(JobRunner(steps=FakeSteps(), jobs_dir=tmp))`)

```python
def test_double_start_is_409(client, company):
    assert client.post(f"/api/companies/{company}/builds", json={}).status_code == 202
    assert client.post(f"/api/companies/{company}/builds", json={}).status_code == 409

def test_status_shows_building(client, company):
    client.post(f"/api/companies/{company}/builds", json={})
    assert client.get(f"/api/companies/{company}").json()["status"] == "building"

def test_dry_run_reports_rebuild(client, company):
    new = {**current_config(client, company), "window": {"since": "2026-06-01"}}
    d = client.put(f"/api/companies/{company}?dry_run=1", json=new).json()
    assert d["rebuild"] is True and d["refetch"] == []

def test_put_needing_rebuild_without_flag_is_409(client, company):
    cfg = current_config(client, company)
    r = client.put(f"/api/companies/{company}", json=with_since(cfg, "2026-06-01"))
    assert r.status_code == 409 and r.json()["detail"]["rebuild_required"]["rebuild"]

def test_put_with_rebuild_starts_rebuild(client, company):
    cfg = current_config(client, company)
    r = client.put(f"/api/companies/{company}?rebuild=1", json=with_since(cfg, "2026-06-01"))
    assert r.status_code == 202 and r.json()["kind"] == "rebuild"

def test_put_slug_mismatch_is_422(client, company):
    cfg = current_config(client, company)
    assert client.put(f"/api/companies/{company}", json={**cfg, "slug": "other"}).status_code == 422

def test_events_stream_starts_with_snapshot(client, company):
    client.post(f"/api/companies/{company}/builds", json={})
    with client.stream("GET", f"/api/companies/{company}/builds/current/events") as s:
        first = next(l for l in s.iter_lines() if l.startswith("event:"))
    assert first == "event: snapshot"
```

- [ ] **Step 2: Run to see them fail.**
- [ ] **Step 3: Implement** with `sse_starlette.EventSourceResponse`.
- [ ] **Step 4: Run to see them pass**, then `make test`.
- [ ] **Step 5: Commit** — `git commit -m "Add build routes, SSE progress and settings save with rebuild"`

---

### Task 8: Overview tools and route

**Files:**
- Create: `apps/backend/queries/tools/recent_work_items.cypher`, `apps/backend/queries/tools/people_activity.cypher`
- Modify: `apps/backend/brain/tools.py` (two `Tool` entries, params and row models)
- Create: `apps/backend/brain/api/overview.py`
- Test: `apps/backend/tests/test_tools.py` (add), `apps/backend/tests/api/test_overview.py`

Before starting: message the session that owns `brain/tools.py` and `queries/tools/` ("Company Brain initial setup") with the two tool names and row shapes below, and adjust names if it objects (spec C10).

**Interfaces:**
- Produces:
  - Tool `recent_work_items` — "Most recent PRs, issues and threads, newest first." Params `RecentParams(limit: int = Field(10, ge=1, le=100))`; row `RecentWorkItem`: `uid, kind, number: int | None, title, state, url: str | None, author: str | None, at: str | None` (latest of created/closed/merged), `systems: list[str]`.
  - Tool `people_activity` — "People with how many PRs they authored and reviewed." Params `ListParams`; row `PersonActivity`: `login, name: str | None, teams: list[str], prs: int, reviews: int`. Bots excluded.
  - `GET /api/companies/{slug}/tools` → `[{name, description, params_schema}]` and `POST /api/companies/{slug}/tools/{name}` body = params → rows, both thin wrappers over `tools.TOOLS` / `tools.call` (spec 6.4). The ask route is not built this round.
  - `GET /api/companies/{slug}/overview` → `Overview`: `slug`, `name`, `since: str`, `counts: list[Stat]` (node kinds only, from `graph_stats`), `recent: list[RecentWorkItem]` (10), `systems: list[SystemSummary]` (from `list_systems`, limit 8), `people: list[PersonActivity]` (limit 8).

- [ ] **Step 1: Write the failing tests** (graph-backed on `synthetic_graph`)

```python
@needs_graph
def test_recent_work_items_newest_first(synthetic_graph):
    rows = tools.call(synthetic_graph, "recent_work_items", limit=5)
    assert len(rows) == 5 and rows[0].uid == "synthetic:issue:14"
    assert [r.at for r in rows] == sorted([r.at for r in rows], reverse=True)

@needs_graph
def test_people_activity_excludes_bots(synthetic_graph):
    logins = {r.login for r in tools.call(synthetic_graph, "people_activity")}
    assert "ci-bot" not in logins and {"alice", "erin"} <= logins

@needs_graph
def test_overview_is_scoped_to_its_company(api_client_with, synthetic_graph):
    empty = "test_empty"; schema.apply_schema(empty)
    client = api_client_with(synthetic_graph, empty)  # writes both YAMLs into a tmp root
    full = client.get(f"/api/companies/{synthetic_graph}/overview").json()
    none = client.get(f"/api/companies/{empty}/overview").json()
    assert full["recent"] and not none["recent"] and not none["people"]
    assert full["slug"] == synthetic_graph and none["slug"] == empty
    db.delete_graph(empty)
```

Check the synthetic data (`examples/synthetic_company`) for the newest item before fixing the expected uid; the frontend sample says `synthetic:issue:14` (10 Sep).

- [ ] **Step 2: Run to see them fail.**
- [ ] **Step 3: Write both Cypher files** with the `//` header and an `// example: make query TOOL=...` line, the tool entries, and the route.
- [ ] **Step 4: Run to see them pass**, plus `make tools` lists the two new tools.
- [ ] **Step 5: Commit** — `git commit -m "Add recent_work_items and people_activity tools and the overview route"`

---

### Task 9: Run targets and docs

**Files:**
- Modify: `Makefile`, `CLAUDE.md` (Commands and a short "API" paragraph under Backend architecture), `.env.example` (`API_PORT=8000`)
- Test: manual run

- [ ] **Step 1: Add targets.** `api: ## API on http://127.0.0.1:$(API_PORT)` → `uv run uvicorn brain.api:app --host 127.0.0.1 --port $(API_PORT) --reload`; `dev: ## API + frontend dev server` running both (`make -j2 api fe-dev`).
- [ ] **Step 2: Verify.** `make up && make synthetic && make api`, then `curl -s localhost:8000/api/companies` lists `falkordb` and `synthetic`, and `curl -s localhost:8000/api/companies/synthetic/overview | head -c 300` returns counts.
- [ ] **Step 3: `make check`** passes (lint + tests).
- [ ] **Step 4: Commit** — `git commit -m "Add make api/dev and document the API"`
