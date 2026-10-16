"""Ingestion pipeline: adapters -> normalize -> loader, one configured source at a time.

Why: this is the glue the CLI calls. It is source-agnostic: it looks up each source's adapter
in the registry, so a new source type needs no change here.

Incremental by default: each source has a SyncState node holding a cursor (the latest
`arrival_at` loaded, a source-server timestamp). Records that arrived before the cursor are
skipped; records without one (people, teams, ownership, links, and git-dated commits and docs)
are always loaded, which is cheap and keeps edges complete.
`full=True` ignores the cursor, and so does a changed `window.since` (widening the window must
pull in records older than the cursor).

After the sources, the embed stage gives new or changed Chunk text its vectors (see
`embeddings.embed_pending`); without a usable model it is skipped, never failed.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from brain import adapters, embeddings, loader
from brain.canonical import CanonicalRecord
from brain.config import CompanyConfig, load_company, raw_dir
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
    embed: embeddings.EmbedReport = field(default_factory=embeddings.EmbedReport)


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
    for source in cfg.sources:
        if only is None or source.type == only:
            yield source, adapters.REGISTRY.get(source.type)


def planned_sources(slug: str, keys: set[str] | None = None) -> tuple[list[str], list[str]]:
    """The source keys `fetch(slug, keys=keys)` and `ingest(slug)` will report on, in order:
    (fetched, ingested). A source with no adapter is reported under its type. Mirrors the
    loops below, so a build job can count its steps before it runs them."""
    fetched: list[str] = []
    ingested: list[str] = []
    for source, adapter in _selected(load_company(slug), None):
        key = adapter.key(source) if adapter is not None else source.type
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
    for source, adapter in _selected(cfg, only):
        if adapter is None:
            if keys is None:
                emit(BuildEvent(slug, "fetch", "skipped", source.type, message=_NO_ADAPTER))
                done.append(f"{source.type}: skipped, {_NO_ADAPTER}")
            continue
        key = adapter.key(source)
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
    for source, adapter in _selected(cfg, only):
        if adapter is None:
            report.sources.append(SourceResult(key=source.type, skipped_reason=_NO_ADAPTER))
            emit(BuildEvent(slug, "records", "skipped", source.type, message=_NO_ADAPTER))
            continue
        key = adapter.key(source)
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
        records = list(normalize(select_new(records, cursor), cfg))
        result.loaded = len(records)
        emit(BuildEvent(slug, "normalize", "done", key, count=result.loaded))

        emit(BuildEvent(slug, "load", "running", key))
        loaded = loader.load(slug, records, origin=key)
        report.load.merge(loaded)
        latest = next_cursor(records, cursor, datetime.now(UTC))
        loader.set_sync_state(slug, adapter.name, key, latest, window_since, result.loaded)
        emit(BuildEvent(slug, "load", "done", key, count=sum(loaded.written.values())))
    report.embed = embeddings.embed_pending(slug, on_event=emit)
    return report
