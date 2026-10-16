"""Adapter for pre-normalised JSONL files (the escape hatch for any tool).

Why: Slack, Jira, Linear or a synthetic demo company can be ingested without writing Python:
convert the export to one JSON object per line, matching the canonical models, and drop the
files in a folder. See docs/canonical-format.md. Every line is validated; a bad line stops
ingestion with its file and line number.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from pydantic import ValidationError

from brain import canonical as c
from brain.adapters.base import SourceUnavailable
from brain.config import CanonicalJsonlSource, CompanyConfig

# file name -> model. Files are optional; order is irrelevant (the loader orders writes).
FILES: dict[str, type[c.Record]] = {
    "people.jsonl": c.Person,
    "teams.jsonl": c.Team,
    "systems.jsonl": c.System,
    "work_items.jsonl": c.WorkItem,
    "changes.jsonl": c.Change,
    "documents.jsonl": c.Document,
    "reviews.jsonl": c.Review,
    "comments.jsonl": c.Comment,
    "ownerships.jsonl": c.Ownership,
    "links.jsonl": c.Link,
}


class CanonicalJsonlAdapter:
    name = "canonical_jsonl"

    def key(self, source: CanonicalJsonlSource) -> str:
        return f"{self.name}:{source.path.as_posix()}"

    def fetch(self, company: CompanyConfig, source: CanonicalJsonlSource, cache_dir: Path) -> None:
        """Nothing to download: the files are already local."""

    def records(
        self, company: CompanyConfig, source: CanonicalJsonlSource, cache_dir: Path
    ) -> Iterator[c.CanonicalRecord]:
        folder = company.resolve(source.path)
        if not folder.is_dir():
            raise SourceUnavailable(f"folder {folder} does not exist")
        for filename, model in FILES.items():
            path = folder / filename
            if path.exists():
                yield from _read(path, model)


def _read(path: Path, model: type[c.Record]) -> Iterator[c.CanonicalRecord]:
    with path.open() as fh:
        for lineno, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                data.setdefault("source", "canonical_jsonl")
                yield model.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as e:
                raise ValueError(f"{path}:{lineno}: {e}") from e
