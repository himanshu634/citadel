"""The archive cache: data/raw/<slug>/archive/<source>/<item>.jsonl, one file per archived item.

Why: a rebuild deletes brain_<slug> and re-reads the sources, which cut everything older than
the window. Archived items must come back, so each one is kept as canonical records beside the
raw cache (which `brain/backend reset` keeps), and `pipeline.load_archive` loads them again.

File format: first line `{"type": "meta", ...}` (source key, item id, uid, ref, archived_at,
request, superseded_by), then one `{"type": "<RecordClass>", ...fields}` line per record.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter

from brain import canonical as c
from brain.adapters.canonical_jsonl import FILES
from brain.config import raw_dir

_log = logging.getLogger(__name__)

CLASSES: dict[str, type[c.Record]] = {model.__name__: model for model in FILES.values()}


@dataclass
class ArchiveEntry:
    source_key: str  # the adapter key of the source it came from, e.g. "github:acme/w"
    item_id: str  # the source's id for it, e.g. "github:acme/w#812"
    uid: str  # the uid of the archived WorkItem or Document
    ref: str  # the ref other items carry for it (their `unresolved_refs`)
    archived_at: str  # ISO time it was archived
    request: str  # the question that made someone look for it
    records: list[c.CanonicalRecord]
    # a newer item that replaces this one; re-marked on every load, since a rebuild loads the
    # archive before the windowed item it points at exists
    superseded_by: str | None = None


def _safe(name: str) -> str:
    for ch in "/:#":
        name = name.replace(ch, "_")
    return name


def archive_dir(slug: str) -> Path:
    return raw_dir(slug, "archive")


def write_entry(slug: str, entry: ArchiveEntry) -> Path:
    """Write (or replace) the entry's file; returns its path."""
    path = archive_dir(slug) / _safe(entry.source_key) / f"{_safe(entry.item_id)}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "type": "meta",
        "source_key": entry.source_key,
        "item_id": entry.item_id,
        "uid": entry.uid,
        "ref": entry.ref,
        "archived_at": entry.archived_at,
        "request": entry.request,
        "superseded_by": entry.superseded_by,
    }
    lines = [json.dumps(meta)]
    for rec in entry.records:
        lines.append(json.dumps({"type": type(rec).__name__, **rec.model_dump(mode="json")}))
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(path)
    return path


def _read_entry(path: Path) -> ArchiveEntry:
    meta: dict | None = None
    records: list[c.CanonicalRecord] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        kind = data.pop("type")
        if kind == "meta":
            meta = data
        else:
            records.append(TypeAdapter(CLASSES[kind]).validate_python(data))
    if meta is None:
        raise ValueError(f"{path}: no meta line")
    return ArchiveEntry(records=records, **meta)


def read_entries(slug: str) -> list[ArchiveEntry]:
    """Every archived item of the company, in file-name order. A file that cannot be read is
    skipped with a warning naming it (one bad file must not stop a build)."""
    entries = []
    for path in sorted(archive_dir(slug).glob("*/*.jsonl")):
        try:
            entries.append(_read_entry(path))
        except (OSError, ValueError, KeyError, TypeError) as e:
            _log.warning("skipped unreadable archive file %s: %s", path, e)
    return entries


def archived_uids(slug: str) -> frozenset[str]:
    return frozenset(e.uid for e in read_entries(slug))
