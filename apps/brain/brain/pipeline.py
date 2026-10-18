"""Ingestion pipeline: adapters -> normalize -> loader, one configured source at a time.

Why: this is the glue the CLI calls. It is source-agnostic: it looks up each source's adapter
in the registry, so a new source type needs no change here.

Incremental by default: each source has a SyncState node holding a cursor (the latest
`arrival_at` loaded, a source-server timestamp). Records that arrived before the cursor are
skipped; records without one (people, teams, ownership, links, and git-dated commits and docs)
are always loaded, which is cheap and keeps edges complete.
`full=True` ignores the cursor, and so does a changed `window.since` (widening the window must
pull in records older than the cursor).

After the sources, `embed` runs: text still without chunks, or held whole in one chunk (graphs
built before work items had chunks or long text was cut; the cursor skips old items), is cut
into chunks, then the embed stage gives new or changed Chunk text its vectors (see
`embeddings.embed_pending`); without a usable model it is skipped, never failed.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from brain import adapters, embeddings, loader
from brain.archive.cache import ArchiveEntry, archive_dir, read_entries
from brain.canonical import CanonicalRecord, WorkItem
from brain.config import CompanyConfig, SourceConfig, load_company, raw_dir
from brain.embeddings import EmbedReport
from brain.events import BuildEvent, OnEvent, noop
from brain.normalize import normalize


@dataclass
class SourceResult:
    key: str
    read: int = 0  # records the adapter produced
    loaded: int = 0  # records passed to the loader after incremental filter + normalize
    skipped_reason: str | None = None


@dataclass
class IngestReport:
    sources: list[SourceResult] = field(default_factory=list)
    load: loader.LoadReport = field(default_factory=loader.LoadReport)
    embed: EmbedReport = field(default_factory=EmbedReport)


_NO_ADAPTER = "no adapter registered"


def select_new(records: Iterable[CanonicalRecord], cursor: datetime | None) -> list:
    """Records that arrived at or after the cursor, plus every record without an arrival time."""
    if cursor is None:
        return list(records)
    return [r for r in records if (t := r.arrival_at()) is None or t >= cursor]


def next_cursor(
    records: Iterable[CanonicalRecord], cursor: datetime | None, now: datetime
) -> datetime | None:
    """Latest arrival time loaded, never past `now` (a bad clock must not hide future records)."""
    latest = max((t for r in records if (t := r.arrival_at())), default=cursor)
    return min(latest, now) if latest else None


def _selected(cfg: CompanyConfig, only: str | None):
    """(source, adapter, key) for each source of type `only` (every source when None). The key
    is the adapter's key for the source, or its type when no adapter is registered."""
    for source in cfg.sources:
        if only is None or source.type == only:
            adapter = adapters.REGISTRY.get(source.type)
            yield source, adapter, adapter.key(source) if adapter is not None else source.type


@dataclass
class ConfiguredSource:
    """One `sources:` entry as the next build will see it, found without running one."""

    key: str  # the adapter key, which also keys its SyncState; the type when no adapter exists
    config: SourceConfig
    downloads: bool  # the adapter's fetch does network I/O
    problem: adapters.SourceProblem | None  # why the next build cannot read it, if anything


def configured_sources(slug: str) -> list[ConfiguredSource]:
    """Each configured source in file order, with what would stop the next build reading it
    (the adapter's optional `check`: a folder, an env var; no network)."""
    cfg = load_company(slug)
    out = []
    for source, adapter, key in _selected(cfg, None):
        if adapter is None:
            problem = adapters.SourceProblem(f"No adapter for source type {source.type}")
            out.append(ConfiguredSource(key, source, False, problem))
            continue
        check = getattr(adapter, "check", None)
        problem = check(cfg, source, raw_dir(slug, source.type)) if check else None
        downloads = bool(getattr(adapter, "downloads", False))
        out.append(ConfiguredSource(key, source, downloads, problem))
    return out


def planned_sources(slug: str, keys: set[str] | None = None) -> tuple[list[str], list[str]]:
    """The source keys `fetch(slug, keys=keys)` and `ingest(slug)` will report on, in order:
    (fetched, ingested). A source with no adapter is reported under its type. Mirrors the
    loops below, so a build job can count its steps before it runs them."""
    fetched: list[str] = []
    ingested: list[str] = []
    for _source, adapter, key in _selected(load_company(slug), None):
        if keys is None or (adapter is not None and key in keys):
            fetched.append(key)
        ingested.append(key)
    return fetched, ingested


def fetch(
    slug: str,
    only: str | None = None,
    keys: set[str] | None = None,
    on_event: OnEvent | None = None,
) -> list[str]:
    """Network step: let each adapter pull raw data into data/raw/<slug>/<type>/.

    `keys` limits the step to those adapter keys (e.g. 'github:acme/widgets').
    """
    emit = on_event or noop
    cfg = load_company(slug)
    done = []
    for source, adapter, key in _selected(cfg, only):
        if adapter is None:
            if keys is None:
                emit(BuildEvent(slug, "fetch", "skipped", key, message=_NO_ADAPTER))
                done.append(f"{key}: skipped, {_NO_ADAPTER}")
            continue
        if keys is not None and key not in keys:
            continue
        emit(BuildEvent(slug, "fetch", "running", key))
        try:
            adapter.fetch(cfg, source, raw_dir(slug, source.type))
        except Exception as e:
            emit(BuildEvent(slug, "fetch", "failed", key, message=str(e)))
            raise
        emit(BuildEvent(slug, "fetch", "done", key))
        done.append(key)
    return done


def load_entries(slug: str, cfg: CompanyConfig, entries: list[ArchiveEntry]) -> loader.LoadReport:
    """Load archived items into brain_<slug>: each entry normalized with its item kept past the
    window, loaded under its own origin (`archive:<source>:<item>`, so a source's BLOCKS prune
    and another entry's load never remove its edges), flagged archived, then every ref that
    points at an archived node resolved and every supersession marked (`report.superseded`
    holds the pairs whose newer item exists). No SyncState: the archive has no cursor."""
    report = loader.LoadReport()
    rows = []
    for e in entries:
        keep = frozenset({e.uid, *(r.uid for r in e.records if isinstance(r, WorkItem))})
        records = list(normalize(e.records, cfg, keep=keep))
        report.merge(loader.load(slug, records, origin=f"archive:{e.source_key}:{e.item_id}"))
        rows.append(
            {"uid": e.uid, "ref": e.ref, "archived_at": e.archived_at, "request": e.request}
        )
    loader.mark_archived(slug, rows)
    loader.resolve_refs(slug)
    report.superseded = supersede(slug, entries)
    return report


def supersede(slug: str, entries: list[ArchiveEntry]) -> dict[str, str]:
    """Mark each entry's `superseded_by`; returns the pairs marked (both nodes exist)."""
    return {
        e.uid: e.superseded_by
        for e in entries
        if e.superseded_by and loader.mark_superseded(slug, e.uid, e.superseded_by)
    }


def load_archive(slug: str, cfg: CompanyConfig) -> loader.LoadReport:
    """Load every item in the company's archive cache (what a rebuild brings back)."""
    return load_entries(slug, cfg, read_entries(slug))


def clear_archive(slug: str) -> int:
    """Delete the archive cache; returns the files removed. The graph keeps the archived items
    until the next rebuild."""
    folder = archive_dir(slug)
    count = sum(1 for _ in folder.glob("*/*.jsonl"))
    shutil.rmtree(folder, ignore_errors=True)
    return count


def ingest(
    slug: str,
    full: bool = False,
    only: str | None = None,
    on_event: OnEvent | None = None,
) -> IngestReport:
    """Transform step: cached/local data -> canonical records -> graph brain_<slug>, then the
    embed stage over every pending chunk (also when `only` limits the sources)."""
    emit = on_event or noop
    cfg = load_company(slug)
    window_since = cfg.window.since.isoformat()
    report = IngestReport()
    entries = read_entries(slug)
    archived = frozenset(e.uid for e in entries)
    report.load.merge(load_entries(slug, cfg, entries))
    for source, adapter, key in _selected(cfg, only):
        if adapter is None:
            report.sources.append(SourceResult(key=key, skipped_reason=_NO_ADAPTER))
            emit(BuildEvent(slug, "records", "skipped", key, message=_NO_ADAPTER))
            continue
        result = SourceResult(key=key)
        report.sources.append(result)
        emit(BuildEvent(slug, "records", "running", key))
        try:
            records = list(adapter.records(cfg, source, raw_dir(slug, source.type)))
        except adapters.SourceUnavailable as e:
            result.skipped_reason = str(e)
            emit(BuildEvent(slug, "records", "skipped", key, message=str(e)))
            continue
        result.read = len(records)
        emit(BuildEvent(slug, "records", "done", key, count=result.read))

        cursor = None if full else loader.get_cursor(slug, key, window_since)
        records = list(normalize(select_new(records, cursor), cfg, keep=archived))
        result.loaded = len(records)
        emit(BuildEvent(slug, "normalize", "done", key, count=result.loaded))

        emit(BuildEvent(slug, "load", "running", key))
        loaded = loader.load(slug, records, origin=key)
        report.load.merge(loaded)
        latest = next_cursor(records, cursor, datetime.now(UTC))
        loader.set_sync_state(slug, adapter.name, key, latest, window_since, result.loaded)
        emit(BuildEvent(slug, "load", "done", key, count=sum(loaded.written.values())))
    loader.resolve_refs(slug)  # items the sources just loaded may point at archived ones
    report.load.superseded.update(supersede(slug, entries))  # their newer items exist now
    report.embed = embed(slug, on_event=emit)
    return report


def embed(slug: str, everything: bool = False, on_event: OnEvent | None = None) -> EmbedReport:
    """The embed step, as ingest ends and `brain embed` runs it: first cut the text that graphs
    built before chunking still hold whole (`loader.backfill_chunks`), then give every pending
    chunk its vector. `everything` embeds every chunk again."""
    loader.backfill_chunks(slug)
    return embeddings.embed_pending(slug, everything=everything, on_event=on_event)
