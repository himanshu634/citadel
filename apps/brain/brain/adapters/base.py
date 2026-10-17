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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from brain.canonical import CanonicalRecord
from brain.config import CompanyConfig, SourceConfig


class SourceUnavailable(Exception):
    """The source cannot be read right now (missing folder, no cache yet). Ingest skips it."""


@dataclass(frozen=True)
class SourceProblem:
    """Why the next build cannot read a source, found without running one (see `Adapter.check`).
    `blocks`: the download step fails, so the whole build fails until it is fixed; otherwise
    ingest only skips this source. `message` names repo-relative paths, never absolute ones."""

    message: str
    blocks: bool = False


class Adapter(Protocol):
    name: str  # the `type` used in companies/<slug>.yaml
    source_model: type[SourceConfig]  # validates that source's entry in the company YAML

    def key(self, source: Any) -> str:
        """Stable id of one configured source, e.g. 'github:FalkorDB/FalkorDB'. Keys SyncState."""
        ...

    def fetch(self, company: CompanyConfig, source: Any, cache_dir: Path) -> None: ...

    # Optional (pipeline.configured_sources reads them with getattr):
    # downloads: bool  -- True when `fetch` does network I/O (default False)
    # def check(self, company, source, cache_dir) -> SourceProblem | None
    #     A cheap look (a folder, an env var) at what would stop the next build reading it.

    def records(
        self, company: CompanyConfig, source: Any, cache_dir: Path
    ) -> Iterator[CanonicalRecord]: ...
