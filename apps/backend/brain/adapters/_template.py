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

from brain.adapters.base import SourceUnavailable
from brain.canonical import CanonicalRecord, WorkItem
from brain.config import CompanyConfig, SourceConfig


class TemplateSource(SourceConfig):
    """Validates this source's entry under `sources:` in companies/<slug>.yaml."""

    type: Literal["template"]
    team: str  # whatever settings the source needs


class TemplateAdapter:
    name = "template"
    source_model = TemplateSource

    def key(self, source: TemplateSource) -> str:
        return f"{self.name}:{source.team}"

    def fetch(self, company: CompanyConfig, source: TemplateSource, cache_dir: Path) -> None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        # page = httpx.get(...).json()
        # (cache_dir / "page_0001.json").write_text(json.dumps(page))

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
