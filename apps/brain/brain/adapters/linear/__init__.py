"""Linear source adapter: tickets of one workspace.

Why: Linear holds the planned work that GitHub history cannot show (who a ticket was for, what it
blocks). `fetch` pulls issues into a cache through the GraphQL API; `records` turns that cache into
canonical records without touching the network. See client.py, fetch.py and transform.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from brain.adapters.linear import fetch as _fetch
from brain.adapters.linear import transform as _transform
from brain.adapters.linear.source import LinearSource
from brain.canonical import CanonicalRecord
from brain.config import CompanyConfig


class LinearAdapter:
    name = "linear"
    source_model = LinearSource

    def key(self, source: LinearSource) -> str:
        return f"{self.name}:{source.workspace}"

    def cache_for(self, source: LinearSource, cache_dir: Path) -> Path:
        return cache_dir / source.workspace

    def fetch(self, company: CompanyConfig, source: LinearSource, cache_dir: Path) -> None:
        _fetch.run(company, source, self.cache_for(source, cache_dir))

    def records(
        self, company: CompanyConfig, source: LinearSource, cache_dir: Path
    ) -> Iterator[CanonicalRecord]:
        return _transform.records(company, source, self.cache_for(source, cache_dir))


__all__ = ["LinearAdapter", "LinearSource"]
