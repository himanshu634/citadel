"""Linear source adapter: tickets of one workspace.

Why: Linear holds the planned work that GitHub history cannot show (who a ticket was for, what it
blocks). `fetch` pulls issues into a cache through the GraphQL API; `records` turns that cache into
canonical records without touching the network. See client.py, fetch.py and transform.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from brain.adapters.base import SourceProblem
from brain.adapters.linear import fetch as _fetch
from brain.adapters.linear import transform as _transform
from brain.adapters.linear.source import LinearSource
from brain.adapters.runs import unfinished
from brain.canonical import CanonicalRecord
from brain.config import CompanyConfig, get_settings


class LinearAdapter:
    name = "linear"
    source_model = LinearSource
    downloads = True

    def key(self, source: LinearSource) -> str:
        return f"{self.name}:{source.workspace}"

    def cache_for(self, source: LinearSource, cache_dir: Path) -> Path:
        return cache_dir / source.workspace

    def fetch(
        self, company: CompanyConfig, source: LinearSource, cache_dir: Path, full: bool = False
    ) -> None:
        _fetch.run(company, source, self.cache_for(source, cache_dir), full=full)

    def check(
        self, company: CompanyConfig, source: LinearSource, cache_dir: Path
    ) -> SourceProblem | None:
        """Every build downloads first, and that needs the API key."""
        if get_settings().linear_api_key:
            return None
        return SourceProblem("No Linear API key: set LINEAR_API_KEY in .env", blocks=True)

    def incomplete(
        self, company: CompanyConfig, source: LinearSource, cache_dir: Path
    ) -> str | None:
        """A sentence while the issue run has not completed (its cache lacks tickets that must
        still pass the ingest cursor), else None."""
        return unfinished(self.cache_for(source, cache_dir) / "issues")

    def records(
        self, company: CompanyConfig, source: LinearSource, cache_dir: Path
    ) -> Iterator[CanonicalRecord]:
        return _transform.records(company, source, self.cache_for(source, cache_dir))


__all__ = ["LinearAdapter", "LinearSource"]
