"""The adapter interface.

Why: an adapter is the only code that knows about one kind of source (GitHub, a docs folder,
a JSONL export). It has two halves:
- `fetch` does network I/O and writes raw responses under data/raw/<slug>/<adapter>/
  (resumable, cached). Sources without a network step make it a no-op.
- `records` is a pure transform from that cache (or a local folder) to canonical records.
  No network, so re-running ingestion costs no API calls and tests can use fixture files.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol

from brain.canonical import CanonicalRecord
from brain.config import CompanyConfig


class SourceUnavailable(Exception):
    """The source cannot be read right now (missing folder, no cache yet). Ingest skips it."""


class Adapter(Protocol):
    name: str  # the `type` used in companies/<slug>.yaml

    def key(self, source: Any) -> str:
        """Stable id of one configured source, e.g. 'github:FalkorDB/FalkorDB'. Keys SyncState."""
        ...

    def fetch(self, company: CompanyConfig, source: Any, cache_dir: Path) -> None: ...

    def records(
        self, company: CompanyConfig, source: Any, cache_dir: Path
    ) -> Iterator[CanonicalRecord]: ...
