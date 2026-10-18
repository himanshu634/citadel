"""The adapter interface.

Why: an adapter is the only code that knows about one kind of source (GitHub, a docs folder,
a JSONL export). It has two halves:
- `fetch` does network I/O and writes raw responses under data/raw/<slug>/<adapter>/
  (resumable, cached; `full` ignores what an earlier fetch already pulled and starts at the
  window). Sources without a network step make it a no-op.
- `records` is a pure transform from that cache (or a local folder) to canonical records.
  No network, so re-running ingestion costs no API calls and tests can use fixture files.
- `incomplete` (optional) says when the cache is not all the source holds for the window: a
  fetch run that never finished, or one not run yet. Ingest then loads what there is but keeps
  its cursor, so the records still to come are not skipped as "already seen" later.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from brain.canonical import CanonicalRecord
from brain.config import CompanyConfig, PathSource, SourceConfig


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

    def fetch(
        self, company: CompanyConfig, source: Any, cache_dir: Path, full: bool = False
    ) -> None:
        """Pull the source into the cache. `full` ignores the earlier fetches' progress and
        pulls the whole window again (the records already cached are kept)."""
        ...

    # Optional (the pipeline reads them with getattr):
    # downloads: bool  -- True when `fetch` does network I/O (default False)
    # def check(self, company, source, cache_dir) -> SourceProblem | None
    #     A cheap look (a folder, an env var) at what would stop the next build reading it.
    # def incomplete(self, company, source, cache_dir) -> str | None
    #     A sentence saying what `records` cannot yet read (a fetch run still unfinished), or
    #     None when the cache is complete. Ingest keeps its cursor while it is not.

    def records(
        self, company: CompanyConfig, source: Any, cache_dir: Path
    ) -> Iterator[CanonicalRecord]: ...


class FolderAdapter:
    """Mixin for a source that is a local folder (`PathSource`): nothing to download, keyed by
    its path, and a problem when the folder is missing."""

    name: str

    def key(self, source: PathSource) -> str:
        return f"{self.name}:{source.path.as_posix()}"

    def fetch(
        self, company: CompanyConfig, source: PathSource, cache_dir: Path, full: bool = False
    ) -> None:
        """Nothing to download: the files are already local."""

    def check(
        self, company: CompanyConfig, source: PathSource, cache_dir: Path
    ) -> SourceProblem | None:
        if company.resolve(source.path).is_dir():
            return None
        return SourceProblem(f"Folder {source.path.as_posix()} does not exist")

    def folder(self, company: CompanyConfig, source: PathSource) -> Path:
        """The source's folder, resolved; SourceUnavailable when it does not exist."""
        folder = company.resolve(source.path)
        if not folder.is_dir():
            raise SourceUnavailable(f"folder {folder} does not exist")
        return folder


def first_heading(text: str) -> str | None:
    """Text of the first `# ` markdown heading (may be ""), or None when there is none."""
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None
