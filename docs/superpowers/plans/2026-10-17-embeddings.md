# Embeddings (Semantic Search) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Embed the text in each company graph (comments, PR/issue/ticket bodies, documents) and give
the agent a `semantic_search` tool that finds evidence by meaning, then follows the graph from each
hit to its work item or document, its author and its systems.

**Architecture:** Every searchable text becomes a `Chunk` node `-[:FROM]->` its source (comments
already do). A new `embed` stage after ingest finds chunks whose text changed since they were last
embedded, embeds them in batches and writes `vecf32` vectors through the loader. The existing HNSW
index on `Chunk.embedding` serves a new named tool, `semantic_search`, which embeds the question,
calls `db.idx.vector.queryNodes`, keeps the best chunk per source node and returns citable rows.

**Tech Stack:** FalkorDB vector index (HNSW, cosine), `fastembed` (ONNX, no torch) with
`BAAI/bge-base-en-v1.5` (768 dimensions), pydantic, pytest, SvelteKit (build progress only).

**Spec:** No separate design doc; the user asked to skip the questions. The design decisions are
in this plan's "Decisions" section, taken from the conversation of 2026-10-17 (what semantic
search is, why to adopt it, then "plan to adopt embedding").

## Decisions (my calls; the user did not choose them)

- **Local model, no API key:** fastembed + `BAAI/bge-base-en-v1.5`, 768 dims, the current
  `EMBEDDING_DIM` default. It sits behind an `Embedder` protocol, so a hosted model (for example
  Voyage) can be added later as another provider without touching the pipeline or the tool.
- **One vector index, on `Chunk` only.** WorkItem and Document text gets its own Chunk nodes
  instead of embeddings on WorkItem/Document, so the search has one index and one result shape.
- **Embedding is incremental by text hash.** Re-ingest with unchanged text embeds nothing; a new
  model name re-embeds everything.
- **A missing model never fails a build.** If the provider is off or the model cannot load, the
  `embed` stage is `skipped` with a sentence, and `semantic_search` returns an error result the
  agent can read.
- **Full-text search stays.** `related_work_items` / `related_documents` remain for exact names,
  numbers and keys; hybrid ranking is out of scope (see Non-goals).

## Non-goals

- Hybrid (vector + full-text + graph) ranking in one tool. Measure the gain from the separate tool
  first (Task 5's eval cases).
- Embedding commit messages (`Change`), reviews (no body field) or chat history in `agent_<slug>`.
- A hosted embedding provider. The protocol leaves room for one; none ships in this plan.
- Showing similarity scores or Chunk nodes on the Graph page.

## Global Constraints

- Dependency rule stays: backend -> agents -> brain. All embedding code lives in `apps/brain`.
- Python holds no Cypher strings: every new query is a `apps/brain/queries/<folder>/<name>.cypher`
  file with the `// purpose / params / returns / example` header.
- `brain/loader.py` stays the only writer to FalkorDB; `brain/db.py` stays the only connection.
- `adapter.records` and `normalize` stay pure; nothing in them calls the model.
- `agents/system_prompt.md` and the tool list stay static (no dates), so the prompt prefix caches.
- No embedding vector ever appears in a tool's rows, `get_entity` output or the Graph page.
- Settings: `EMBEDDING_PROVIDER` (`fastembed` | `none`, default `fastembed`),
  `EMBEDDING_MODEL` (default `BAAI/bge-base-en-v1.5`), `EMBEDDING_DIM` (default `768`).
- Model files cache in `data/models/` (already git-ignored by `data/*`).
- Nothing in `make test` downloads the model; tests use a deterministic fake embedder.
- Lint: `make lint` (ruff, line length 100, py312) and `make fe-check` must pass.

## Review Focus

1. **Offline or provider off.** `EMBEDDING_PROVIDER=none`, or the model cannot download: `make
   synthetic` and a UI build still finish; the embed stage says why it skipped; `semantic_search`
   answers with an `is_error` sentence, never a stack trace. (Task 3, Task 4 tests.)
2. **Re-ingest costs nothing.** A second `ingest` with the same data embeds 0 chunks; editing one
   comment re-embeds exactly that chunk. (Task 3 test.)
3. **Model change.** Setting a different `EMBEDDING_MODEL` re-embeds every chunk, even with
   unchanged text. (Task 3 test.)
4. **Documents that shrink.** A document re-ingested with fewer paragraphs leaves no stale chunks
   behind to be found by search. (Task 2 test.)
5. **New chunk kinds leak into old views.** The Graph page's per-node `comments` count and
   `get_entity`'s neighbours must not count body/document chunks as comments, and must not carry
   vectors. (Task 2 test.)

---

## File Structure

| File | Responsibility |
|---|---|
| `apps/brain/brain/embeddings.py` (new) | `Embedder` protocol, `FastEmbedEmbedder`, `get_embedder` / `set_embedder`, `embed_pending` (the embed stage) |
| `apps/brain/brain/chunking.py` (new) | pure text helpers: `split_text`, `text_hash` |
| `apps/brain/brain/loader.py` | writes the new chunk kinds, prunes document chunks, writes embeddings |
| `apps/brain/brain/pipeline.py` | runs the embed stage after the ingest loop |
| `apps/brain/brain/tools.py` | `semantic_search` params, row, prepare |
| `apps/brain/brain/testing.py` | `FakeEmbedder`, `embedded_graph` fixture |
| `apps/brain/queries/load/` | `work_item_chunk`, `document_chunk`, `prune_document_chunks`, `chunks_to_embed`, `chunk_embedding` |
| `apps/brain/queries/tools/semantic_search.cypher` (new) | the vector query + graph hop |
| `apps/brain/queries/graph/nodes.cypher` | counts comment chunks only |
| `apps/agents/agents/walk.py`, `system_prompt.md`, `evals/cases/synthetic.yaml` | agent side |
| `apps/backend/backend/jobs.py`, `apps/frontend/src/lib/types.ts`, `buildProgress.ts` | the `embed` build stage |

---

### Task 1: Embedder interface, settings and the fake

**Files:**
- Create: `apps/brain/brain/embeddings.py`
- Modify: `apps/brain/brain/config.py` (Settings, next to `embedding_dim`), `apps/brain/pyproject.toml`,
  `apps/brain/brain/testing.py`, `.env.example`
- Test: `apps/brain/tests/test_embeddings.py` (new)

**Interfaces:**
- Produces:
  - `class Embedder(Protocol)`: `model: str`, `dim: int`,
    `passages(texts: list[str]) -> list[list[float]]`, `query(text: str) -> list[float]`
  - `class EmbeddingUnavailable(RuntimeError)` — message is a sentence for a person
  - `class FastEmbedEmbedder` (implements `Embedder`; builds `fastembed.TextEmbedding(model_name,
    cache_dir=REPO_ROOT / "data/models")` lazily on first call; `passages` uses
    `passage_embed`, `query` uses `query_embed`; `check_dim(actual: int) -> None` raises
    `EmbeddingUnavailable` when the loaded model's dimension is not `EMBEDDING_DIM`, and runs
    right after load)
  - `get_embedder() -> Embedder | None` — `None` when `EMBEDDING_PROVIDER=none`; one instance per
    process
  - `set_embedder(e: Embedder | None) -> None` — test/override hook; `set_embedder(None)` restores
    the settings-based default
  - `brain.testing.FakeEmbedder(dim: int = 768, model: str = "fake")` — bag-of-words: each word
    (lowercased, `\w+`) adds 1.0 to bucket `int(sha256(word)) % dim`, then L2-normalised; an empty
    text gives a zero vector
  - Settings: `embedding_provider: Literal["fastembed", "none"] = "fastembed"`,
    `embedding_model: str = "BAAI/bge-base-en-v1.5"`

- [ ] **Step 1: Write the failing tests**

```python
def test_fake_embedder_is_deterministic_and_normalised():
    e = FakeEmbedder(dim=16)
    a, b = e.passages(["Login breaks after token refresh", "login breaks after token refresh"])
    assert a == b and abs(sum(x * x for x in a) - 1.0) < 1e-6 and len(a) == 16

def test_provider_none_gives_no_embedder(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "none")
    get_settings.cache_clear(); set_embedder(None)
    assert get_embedder() is None

def test_set_embedder_overrides_and_resets():
    fake = FakeEmbedder()
    set_embedder(fake)
    assert get_embedder() is fake
    set_embedder(None)
    assert get_embedder() is not fake

def test_fastembed_dimension_mismatch_is_a_sentence(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DIM", "384")
    get_settings.cache_clear()
    e = FastEmbedEmbedder("BAAI/bge-base-en-v1.5", dim=384)
    with pytest.raises(EmbeddingUnavailable, match="768.*EMBEDDING_DIM=384"):
        e.check_dim(768)   # the model's real dimension, checked after load
```

(`get_settings` in `brain/config.py` is `lru_cache`d, hence the `cache_clear()`; add an autouse
fixture in the test file that clears it and calls `set_embedder(None)` after each test.)

- [ ] **Step 2: Run to verify they fail**

Run: `make test ARGS="apps/brain/tests/test_embeddings.py"`
Expected: FAIL, `ModuleNotFoundError: brain.embeddings`

- [ ] **Step 3: Implement** `embeddings.py`, the two settings, `FakeEmbedder` in `testing.py`.
  Add `fastembed>=0.7` to `apps/brain/pyproject.toml` and run `uv sync`. Add
  `EMBEDDING_PROVIDER=fastembed` and `EMBEDDING_MODEL=BAAI/bge-base-en-v1.5` under
  `EMBEDDING_DIM` in `.env.example`, each with a one-line comment. `FastEmbedEmbedder` wraps
  any load/download failure in `EmbeddingUnavailable("Could not load embedding model <name>: <why>")`.

- [ ] **Step 4: Run to verify they pass**

Run: `make test ARGS="apps/brain/tests/test_embeddings.py"` → PASS. `make lint` → clean.

- [ ] **Step 5: Commit** — `git commit -m "Embeddings: Embedder protocol, fastembed provider, fake for tests"`

---

### Task 2: Chunks for work-item bodies and documents

**Files:**
- Create: `apps/brain/brain/chunking.py`, `apps/brain/queries/load/work_item_chunk.cypher`,
  `apps/brain/queries/load/document_chunk.cypher`, `apps/brain/queries/load/prune_document_chunks.cypher`
- Modify: `apps/brain/brain/loader.py` (next to the `load/comment_chunk` call, ~line 280),
  `apps/brain/queries/load/comment_chunk.cypher` (also `SET c.text_hash = row.text_hash`),
  `apps/brain/queries/graph/nodes.cypher` (line 10: `WHERE c.kind = 'comment'`)
- Test: `apps/brain/tests/test_chunking.py` (new, pure), `apps/brain/tests/test_graph.py`

**Interfaces:**
- Produces:
  - `chunking.split_text(text: str, max_chars: int = 1200) -> list[str]` — splits on blank lines,
    packs paragraphs up to `max_chars`, hard-splits a paragraph longer than `max_chars` on the last
    space before the limit; strips; drops empty pieces; `""` -> `[]`
  - `chunking.text_hash(text: str) -> str` — first 16 hex chars of sha256 of the UTF-8 text
  - Chunk node properties (all kinds): `uid, company, kind, text, text_hash, source, url` plus
    `ts`/`created_at` where the source has them. Kinds and uids:
    - `comment`: `chunk:<comment uid>` (exists)
    - `work_item`: `chunk:<work item uid>:body`, text = `title + "\n\n" + body` (title alone when
      body is empty)
    - `document`: `chunk:<document uid>:<i>` for `i` in `0..n-1`, from `split_text(title + "\n\n" + body)`;
      the row carries `idx: i` and `document_chunk.cypher` sets `c.idx = row.idx`
  - `load/prune_document_chunks` params `$rows: [{doc_uid, keep}]` (`keep` = that document's chunk
    count in this load): `DETACH DELETE`s Chunks FROM that document with `c.idx >= keep`

- [ ] **Step 1: Write the failing tests**

```python
# test_chunking.py
def test_split_packs_paragraphs_and_hard_splits_long_ones():
    text = "a" * 10 + "\n\n" + "b" * 10 + "\n\n" + ("word " * 400)
    parts = split_text(text, max_chars=1200)
    assert parts[0] == "a" * 10 + "\n\n" + "b" * 10
    assert all(len(p) <= 1200 for p in parts) and len(parts) == 3

def test_split_empty_and_hash_stable():
    assert split_text("  \n\n ") == []
    assert text_hash("x") == text_hash("x") != text_hash("y") and len(text_hash("x")) == 16

# test_graph.py
def test_bodies_and_documents_become_chunks(synthetic_graph):
    issue = tools.get_entity(synthetic_graph, uid="synthetic:issue:14")
    chunks = [n for n in issue.neighbours if n.label == "Chunk" and n.rel == "FROM"]
    assert {n.uid for n in chunks} == {"chunk:synthetic:issue:14:body", "chunk:synthetic:comment:7"}
    doc = tools.get_entity(synthetic_graph, uid="synthetic:doc:docs/billing-runbook.md")
    assert any(n.uid == "chunk:synthetic:doc:docs/billing-runbook.md:0" for n in doc.neighbours)
    rows = {r["uid"]: r for r in db.run(synthetic_graph, "graph/nodes", read_only=True)}
    assert rows["synthetic:issue:14"]["comments"] == 1    # its body chunk is not a comment
    assert rows["synthetic:pr:3"]["comments"] == 2

def test_shrunk_document_leaves_no_stale_chunks():          # Review Focus 4
    slug = "test_doc_shrink"
    db.delete_graph(slug)
    long = "\n\n".join(("para%d " % i) * 200 for i in range(3))   # 3 chunks at 1200 chars
    doc = lambda body: Document(uid="t:doc:a.md", source="t", path="a.md", title="A", body=body)
    loader.load(slug, [doc(long)])
    loader.load(slug, [doc("one short paragraph")])
    rows = db.run_text(slug, "MATCH (c:Chunk)-[:FROM]->(:Document) RETURN c.uid AS uid")
    assert [r["uid"] for r in rows] == ["chunk:t:doc:a.md:0"]
    db.delete_graph(slug)
```

(Neighbour fields come from `get_entity.cypher`: `rel, direction, uid, label, title, url`.
Comment 7 is issue 14's only comment and PR 3 has comments 3 and 4, per `COMMENTS` in
`apps/brain/examples/synthetic_company/generate.py`. Build `Document` with whatever other
required fields `canonical.Document` / `Record` has; skip the shrink test when `falkordb_up()` is
false. If `db.run_text` cannot take a read query, add a one-line test-only `.cypher` under
`apps/brain/tests/fixtures/` instead.)

- [ ] **Step 2: Run to verify they fail** — `make test ARGS="apps/brain/tests/test_chunking.py
  apps/brain/tests/test_graph.py"` → FAIL (module missing; body chunk not found).

- [ ] **Step 3: Implement.** Loader builds rows with `text_hash` for all three kinds, runs
  `load/work_item_chunk` after WorkItem nodes and `load/document_chunk` then
  `load/prune_document_chunks` after Document nodes. Both new chunk queries `MATCH` the source
  then `MERGE (c:Chunk {uid})`, `SET` the properties, `MERGE (c)-[:FROM]->(source)`, like
  `comment_chunk.cypher`. Chunks are written only for records in this load, so incremental ingest
  touches only changed items.

- [ ] **Step 4: Run to verify they pass** — same command → PASS; then `make test` → all green
  (the `test_ingesting_twice_gives_identical_counts` test must still pass).

- [ ] **Step 5: Commit** — `git commit -m "Brain: Chunk nodes for work-item bodies and documents"`

---

### Task 3: The embed stage

**Files:**
- Create: `apps/brain/queries/load/chunks_to_embed.cypher`, `apps/brain/queries/load/chunk_embedding.cypher`,
  `apps/brain/queries/load/clear_embedded.cypher`
- Modify: `apps/brain/brain/embeddings.py`, `apps/brain/brain/loader.py`, `apps/brain/brain/pipeline.py`,
  `apps/brain/brain/events.py` (`Stage` gains `"embed"`), `apps/brain/brain/cli.py`
  (`brain embed SLUG [--all]`), `Makefile` (`embed` target; `synthetic` runs it after ingest),
  `apps/brain/brain/testing.py` (`embedded_graph` fixture)
- Test: `apps/brain/tests/test_embed_stage.py` (new, needs `make up`), `apps/brain/tests/test_pipeline_events.py`

**Interfaces:**
- Consumes: Task 1 `Embedder`, `get_embedder`, `EmbeddingUnavailable`, `FakeEmbedder`; Task 2 `text_hash` on every Chunk.
- Produces:
  - `load/chunks_to_embed` params `$model, $limit` -> rows `{uid, text, text_hash}` for chunks where
    `c.embedding IS NULL OR c.embedded_hash <> c.text_hash OR c.embed_model <> $model`, ordered by uid
  - `load/chunk_embedding` params `$model, $rows: [{uid, vector, text_hash}]` ->
    `SET c.embedding = vecf32(row.vector), c.embedded_hash = row.text_hash, c.embed_model = $model`
  - `loader.set_embeddings(slug: str, rows: list[dict], model: str) -> int`
  - `@dataclass EmbedReport: embedded: int = 0; skipped_reason: str | None = None`
  - `embeddings.embed_pending(slug: str, embedder: Embedder | None = None, batch: int = 64,
    on_event: OnEvent | None = None, everything: bool = False) -> EmbedReport` — `embedder=None`
    means `get_embedder()`; when that is `None` or raises `EmbeddingUnavailable`, emits
    `BuildEvent(slug, "embed", "skipped", message=...)` and returns the reason; otherwise emits
    `running` then `done` with `count`. `everything=True` (CLI `--all`) first runs
    `load/clear_embedded` (via `loader.clear_embedded(slug) -> int`: `SET c.embedded_hash = NULL`
    on every Chunk) and then the normal loop, so every chunk is pending exactly once. Never force a
    re-embed by passing a model name that cannot match: the same first batch would come back
    forever. Stops when a batch comes back empty or when a write returns 0 (guards an endless loop).
  - `IngestReport.embed: EmbedReport`; `pipeline.ingest` calls `embed_pending` after the source loop
    (also when `only=` limits the sources)
  - `brain.testing.embedded_graph` session fixture: like `synthetic_graph` on slug
    `test_embedded`, then `set_embedder(FakeEmbedder())` and `embed_pending(slug)`; resets with
    `set_embedder(None)` and deletes the graph after.

- [ ] **Step 1: Write the failing tests**

```python
def test_embeds_every_chunk_once_then_nothing(fresh_synthetic):   # throwaway graph per test
    fake = FakeEmbedder()
    first = embed_pending(fresh_synthetic, fake)
    assert first.embedded == count_chunks(fresh_synthetic) > 0
    assert embed_pending(fresh_synthetic, fake).embedded == 0          # Review Focus 2

def test_edited_comment_reembeds_only_that_chunk(fresh_synthetic):
    embed_pending(fresh_synthetic, FakeEmbedder())
    reload_comment(fresh_synthetic, "synthetic:comment:1", body="new words entirely")
    assert embed_pending(fresh_synthetic, FakeEmbedder()).embedded == 1

def test_new_model_reembeds_everything(fresh_synthetic):              # Review Focus 3
    embed_pending(fresh_synthetic, FakeEmbedder(model="a"))
    assert embed_pending(fresh_synthetic, FakeEmbedder(model="b")).embedded == count_chunks(fresh_synthetic)

def test_no_provider_skips_with_a_reason(fresh_synthetic):           # Review Focus 1
    events = []
    set_embedder(None); monkeypatch_provider_none()
    report = embed_pending(fresh_synthetic, on_event=events.append)
    assert report.embedded == 0 and "EMBEDDING_PROVIDER" in report.skipped_reason
    assert events[-1].stage == "embed" and events[-1].status == "skipped"

def test_everything_reembeds_each_chunk_once(fresh_synthetic):
    embed_pending(fresh_synthetic, FakeEmbedder())
    report = embed_pending(fresh_synthetic, FakeEmbedder(), batch=4, everything=True)
    assert report.embedded == count_chunks(fresh_synthetic)          # terminates; no repeats

def test_unloadable_model_skips_not_fails(fresh_synthetic):
    class Broken(FakeEmbedder):
        def passages(self, texts): raise EmbeddingUnavailable("Could not load embedding model x: offline")
    assert "offline" in embed_pending(fresh_synthetic, Broken()).skipped_reason
```

`fresh_synthetic` (a per-test throwaway graph loaded with `brain.testing.load_company`),
`count_chunks`, `reload_comment` (re-loads one `Comment` through `loader.load`) and
`monkeypatch_provider_none` (sets `EMBEDDING_PROVIDER=none`, clears `get_settings`, calls
`set_embedder(None)`) are helpers local to `test_embed_stage.py`; Task 4 imports the last one.

In `test_pipeline_events.py`: the existing ingest event-order test now ends with an `embed` event
(use `set_embedder(FakeEmbedder())` there).

- [ ] **Step 2: Run to verify they fail** — `make test ARGS="apps/brain/tests/test_embed_stage.py"` → FAIL.

- [ ] **Step 3: Implement** the two queries, `loader.set_embeddings`, `embed_pending`, the stage,
  the CLI command (prints `embedded N chunks` or the skip reason in yellow) and `make embed
  SLUG=x [ALL=1]`.

- [ ] **Step 4: Verify** — the test command → PASS; `make test` → green. Then with the real model:
  `make synthetic` prints `embedded N chunks` (first run downloads ~0.2 GB into `data/models/`),
  and a second `make embed SLUG=synthetic` prints `embedded 0 chunks`.

- [ ] **Step 5: Commit** — `git commit -m "Brain: embed stage writes Chunk vectors after ingest"`

---

### Task 4: The `semantic_search` tool

**Files:**
- Create: `apps/brain/queries/tools/semantic_search.cypher`
- Modify: `apps/brain/brain/tools.py` (params, row, `_semantic` prepare, `Tool(...)` entry between
  `related_documents` and `person_profile`, typed wrapper), `apps/brain/brain/cli.py` only if
  `make query` needs the embedder set up (it should not: `prepare` calls `get_embedder()`)
- Test: `apps/brain/tests/test_semantic_search.py` (new, uses `embedded_graph`)

**Interfaces:**
- Consumes: Task 3 `embedded_graph`; Task 1 `get_embedder`.
- Produces:
  - `SemanticParams(text: str, limit: int = 8 (1..30), kinds: list[Literal["comment",
    "work_item", "document"]] | None = None)`
  - `SemanticHit` row: `uid` (the source WorkItem/Document), `label`, `kind` (pr / issue / ticket /
    thread / document), `number: int | None`, `title`, `state: str | None`, `url: str | None`,
    `chunk_uid`, `chunk_kind`, `snippet` (first 300 chars of the best chunk), `similarity: float`
    (0..1, higher is closer), `author: str | None`, `systems: list[str]`
  - Tool description: `"Work items and documents whose text means the same as the question, even
    in other words (semantic search). Use for why/how questions; use related_work_items for exact
    names, numbers and keys."`
  - `_semantic(p)` -> `{"vector": list[float] | None, "k": ..., "limit", "kinds"}` with
    `k = min(limit * 4, 200)`, or `k = 200` when `kinds` is set (the filter runs after the
    nearest-neighbour step, so comments could otherwise crowd out every document; say so in the
    query's `// notes:`);
    `vector` is `None` for blank text; raises `EmbeddingUnavailable("Semantic search is off: set
    EMBEDDING_PROVIDER=fastembed and run make embed.")` when `get_embedder()` is `None`
  - `tools.call` returns `[]` when `query_params.get("vector", ...) is None` (same short-circuit
    as the empty full-text query)
  - Query: `CALL db.idx.vector.queryNodes('Chunk', 'embedding', $k, vecf32($vector)) YIELD node,
    score`, filter by `$kinds` when given, `MATCH (node)-[:FROM]->(src)`, keep the best chunk per
    `src`, then the same one-hop enrichment as `related_work_items` (author, systems) or
    `related_documents` (systems via MENTIONS); `LIMIT $limit`, best first.

- [ ] **Step 1: Find what `score` means.** With `make up` and `make synthetic` done, run a
  one-off query in the FalkorDB Browser (`:3000`) using a chunk's own vector:
  `MATCH (c:Chunk) WITH c LIMIT 1 CALL db.idx.vector.queryNodes('Chunk','embedding',1,c.embedding) YIELD node, score RETURN node.uid = c.uid, score`.
  `score ≈ 0` means it is a cosine **distance** -> `similarity = 1 - score`; `≈ 1` means it is
  already a similarity. Write the answer into the query's header `// notes:` line.

- [ ] **Step 2: Write the failing tests**

```python
def test_finds_a_comment_by_its_words_and_cites_its_work_item(embedded_graph):
    # erin's comment on PR 3 (comment 3 in generate.py): "Rounding is off by a cent for annual plans."
    hits = tools.semantic_search(embedded_graph, text="rounding off by a cent on annual plans")
    assert hits[0].uid == "synthetic:pr:3"     # cited by its PR, not by the chunk
    assert hits[0].chunk_uid in {"chunk:synthetic:comment:3", "chunk:synthetic:pr:3:body"}
    assert hits == sorted(hits, key=lambda h: -h.similarity) and 0 <= hits[-1].similarity <= 1

def test_one_row_per_source_and_kinds_filter(embedded_graph):
    hits = tools.semantic_search(embedded_graph, text="managed postgres", limit=10)
    assert len({h.uid for h in hits}) == len(hits)
    docs = tools.semantic_search(embedded_graph, text="managed postgres", kinds=["document"])
    assert docs and all(h.label == "Document" for h in docs)

def test_blank_text_returns_nothing_without_the_model(embedded_graph):
    assert tools.semantic_search(embedded_graph, text="   ") == []

def test_rows_never_carry_vectors(embedded_graph):                    # Review Focus 5
    row = tools.semantic_search(embedded_graph, text="invoice")[0].model_dump()
    assert not any(isinstance(v, list) and len(v) > 50 for v in row.values())

def test_provider_off_is_an_error_sentence(embedded_graph, monkeypatch):   # Review Focus 1
    monkeypatch_provider_none()
    with pytest.raises(EmbeddingUnavailable, match="Semantic search is off"):
        tools.semantic_search(embedded_graph, text="invoice")
```

Also in `apps/agents/tests/test_toolset.py`: calling `semantic_search` with the provider off gives
a `ToolOutcome` with `is_error=True` and that sentence (the toolset already turns exceptions into
error results).

- [ ] **Step 3: Run to verify they fail** — `make test ARGS="apps/brain/tests/test_semantic_search.py"` → FAIL.

- [ ] **Step 4: Implement** the query and the tool.

- [ ] **Step 5: Verify** — the test command → PASS; `make test` → green; `make tools` lists
  `semantic_search`; with the real model,
  `make query SLUG=synthetic TOOL=semantic_search P="text='why do invoices get charged twice'"`
  returns PR/issue 4 or 14 near the top.

- [ ] **Step 6: Commit** — `git commit -m "Brain: semantic_search tool over Chunk vectors"`

---

### Task 5: The agent uses it

**Files:**
- Modify: `apps/agents/agents/walk.py` (a `_semantic_search` walker in the table at ~line 212),
  `apps/agents/agents/system_prompt.md`, `apps/agents/agents/evals/cases/synthetic.yaml`
- Test: `apps/agents/tests/test_walk.py`, `apps/agents/tests/test_evals.py` (case files still load)

**Interfaces:**
- Consumes: Task 4 `SemanticHit` row fields.
- Produces: walker draws each hit's source node (label from `row["label"]`) and an `inferred` link to
  each of its `systems`, matching how `_related_work_items` draws its rows.

- [ ] **Step 1: Failing test** in `test_walk.py`: `subgraph("semantic_search", {...}, [hit_row])`
  returns the source node with its label and one inferred link per system.
- [ ] **Step 2: Run** `make test ARGS="apps/agents/tests/test_walk.py"` → FAIL.
- [ ] **Step 3: Implement** the walker. In `system_prompt.md`, replace the sentence that allows
  "at most one `related_work_items` search" so that, for a why/how question or when a full-text
  search finds nothing, the agent tries `semantic_search` once; keep it static. Add 3 eval cases
  tagged `[semantic]` whose questions share no key words with the answer's text (paraphrases of
  synthetic comments/issues), each with a gold ref or literal `cite_any`, `tools_any:
  [semantic_search]` and a `max_steps`.
- [ ] **Step 4: Verify** `make test` → green. Then the live check (calls the API):
  `make eval CASE=semantic` (expect most passes), and `make eval` against the last baseline file
  in `data/evals/synthetic/` with `BASELINE=<file>`: no case drops in pass rate.
- [ ] **Step 5: Commit** — `git commit -m "Agents: semantic_search in the walk, prompt and evals"`

---

### Task 6: `embed` in the build progress

**Files:**
- Modify: `apps/backend/backend/jobs.py` in three places: `_plan` (~line 186) appends `"embed"`
  after `_INGEST`, so the trail ends with `("embed", None)`; `_STEP_STAGES` (~line 45) puts
  `"embed"` under the `ingest` step (after the per-source stages, not repeated per source);
  `_after` (~line 193) returns `("embed", None)` after the last source's `load`, so a stop or
  failure during embedding is credited to `embed`, not to a phantom next `records`, `apps/frontend/src/lib/types.ts` (`BuildStage` gains `'embed'`),
  `apps/frontend/src/lib/buildProgress.ts` (a company-wide row like `prepare`, labelled
  "Embed text")
- Test: the backend jobs tests (`apps/backend/tests/`), `apps/frontend/src/lib/buildProgress.test.ts`

- [ ] **Step 1: Failing tests** — backend: a planned ingest job's trail ends with `("embed",
  None)` and the step counter counts it; a job stopped after the last source's `load done`
  gets its closing event on stage `embed`; frontend: a build whose events end with `embed done`
  shows an Embed row after the per-source rows, and `embed skipped` shows its message.
- [ ] **Step 2: Run** `make test ARGS="apps/backend/tests"` and `make fe-test` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify** `make test`, `make fe-test`, `make fe-check` → green. Run `make dev`, start
  a rebuild of `synthetic` from the UI and screenshot the progress table showing the Embed row
  (both themes).
- [ ] **Step 5: Commit** — `git commit -m "Build progress: the embed stage"`

---

### Task 7: Docs

**Files:** `docs/graph-model.md` (Chunk kinds, `text_hash`, `embedded_hash`, `embed_model`,
`embedding`), `CLAUDE.md` (the embed stage in the pipeline diagram, `make embed`, the
`EMBEDDING_*` settings, `semantic_search` beside the full-text tools), the header comment of
`queries/schema/vector_index.cypher` (which tool queries it now).

- [ ] **Step 1:** Update the three files.
- [ ] **Step 2:** `make lint` → clean.
- [ ] **Step 3: Commit** — `git commit -m "Docs: embeddings and semantic search"`
