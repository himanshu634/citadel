"""Ingestion pipeline: adapters -> normalize -> loader, one configured source at a time.

Why: this is the glue the CLI calls. It is source-agnostic: it looks up each source's adapter
in the registry, so a new source type needs no change here.

Incremental by default: each source has a SyncState node holding a cursor (the latest
`arrival_at` loaded, a source-server timestamp). Records that arrived before the cursor are
skipped; records without one (people, teams, ownership, links, and git-dated commits and docs)
are always loaded, which is cheap and keeps edges complete.
`full=True` ignores the cursor, and so does a changed `window.since` (widening the window must
pull in records older than the cursor).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from brain import adapters, loader
from brain.canonical import CanonicalRecord
from brain.config import CompanyConfig, load_company, raw_dir
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


def fetch(slug: str, only: str | None = None) -> list[str]:
    """Network step: let each adapter pull raw data into data/raw/<slug>/<type>/."""
    cfg = load_company(slug)
    done = []
    for source, adapter in _selected(cfg, only):
        if adapter is None:
            done.append(f"{source.type}: skipped, no adapter registered")
            continue
        adapter.fetch(cfg, source, raw_dir(slug, source.type))
        done.append(adapter.key(source))
    return done


def ingest(slug: str, full: bool = False, only: str | None = None) -> IngestReport:
    """Transform step: cached/local data -> canonical records -> graph brain_<slug>."""
    cfg = load_company(slug)
    window_since = cfg.window.since.isoformat()
    report = IngestReport()
    for source, adapter in _selected(cfg, only):
        if adapter is None:
            report.sources.append(
                SourceResult(key=source.type, skipped_reason="no adapter registered")
            )
            continue
        key = adapter.key(source)
        result = SourceResult(key=key)
        report.sources.append(result)
        try:
            records = list(adapter.records(cfg, source, raw_dir(slug, source.type)))
        except adapters.SourceUnavailable as e:
            result.skipped_reason = str(e)
            continue
        result.read = len(records)

        cursor = None if full else loader.get_cursor(slug, key, window_since)
        records = list(normalize(select_new(records, cursor), cfg))
        result.loaded = len(records)

        report.load.merge(loader.load(slug, records))
        latest = next_cursor(records, cursor, datetime.now(UTC))
        loader.set_sync_state(slug, adapter.name, key, latest, window_since, result.loaded)
    return report
