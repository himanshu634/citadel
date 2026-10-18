"""Skeleton for a new source adapter. Copy to <name>.py and fill in.

Steps:
1. Rename TemplateSource / TemplateAdapter and set `type` / `name` (e.g. "linear").
2. Implement fetch (network -> cache_dir) and records (cache_dir -> canonical records).
3. Register it in brain/adapters/__init__.py: "linear": LinearAdapter(),
4. Add `- type: linear` (plus its settings) to a company YAML and run `make sync SLUG=<slug>`.

Rules: `fetch` may use the network and must only write under `cache_dir`. `records` must not
use the network; it reads the cache and yields brain.canonical models. Never emit emails.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from brain.adapters.base import SourceProblem, SourceUnavailable
from brain.canonical import CanonicalRecord, WorkItem
from brain.config import CompanyConfig, SourceConfig


class TemplateSource(SourceConfig):
    """Validates this source's entry under `sources:` in companies/<slug>.yaml."""

    type: Literal["template"]
    team: str  # whatever settings the source needs


class TemplateAdapter:
    name = "template"
    source_model = TemplateSource
    downloads = True  # fetch does network I/O (the Sources page offers Sync for this source)

    def key(self, source: TemplateSource) -> str:
        return f"{self.name}:{source.team}"

    def fetch(
        self, company: CompanyConfig, source: TemplateSource, cache_dir: Path, full: bool = False
    ) -> None:
        """`full`: pull the whole window again instead of only what changed since the last
        fetch (a source that pages through an API should use brain.adapters.runs.fetch_paged,
        which handles both)."""
        cache_dir.mkdir(parents=True, exist_ok=True)
        # page = httpx.get(...).json()
        # (cache_dir / "page_0001.json").write_text(json.dumps(page))

    def check(
        self, company: CompanyConfig, source: TemplateSource, cache_dir: Path
    ) -> SourceProblem | None:
        """Optional: what would stop the next build reading this source (no network)."""
        # if not get_settings().template_api_key:
        #     return SourceProblem("No API key: set TEMPLATE_API_KEY in .env", blocks=True)
        return None

    def incomplete(
        self, company: CompanyConfig, source: TemplateSource, cache_dir: Path
    ) -> str | None:
        """Optional: a sentence when the cache is not all the source holds (a fetch that stopped
        halfway), so ingest loads it but keeps its cursor; None when it is complete."""
        return None

    def records(
        self, company: CompanyConfig, source: TemplateSource, cache_dir: Path
    ) -> Iterator[CanonicalRecord]:
        pages = sorted(cache_dir.glob("page_*.json"))
        if not pages:
            raise SourceUnavailable("no cached pages; run `make fetch` first")
        for page in pages:
            for item in json.loads(page.read_text()):
                yield WorkItem(
                    uid=f"{self.name}:{item['id']}",
                    source=self.name,
                    url=item.get("url"),
                    kind="ticket",
                    title=item["title"],
                    state=item["state"],
                    created_at=item["created_at"],
                    author_login=item.get("author"),
                )
