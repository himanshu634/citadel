"""Adapter for a folder of markdown / text files a company has published.

Why: design docs, ADRs and runbooks often live outside the code host. Dropping them in a folder
turns each file into a Document node that agents can search and cite.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from brain.adapters.base import SourceUnavailable
from brain.canonical import CanonicalRecord, Document
from brain.config import CompanyConfig, LocalDocsSource

SUFFIXES = {".md", ".markdown", ".txt"}


def doc_title(path: Path, body: str) -> str:
    """First markdown heading, else the file name."""
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("-", " ").replace("_", " ")


class LocalDocsAdapter:
    name = "local_docs"

    def key(self, source: LocalDocsSource) -> str:
        return f"{self.name}:{source.path.as_posix()}"

    def fetch(self, company: CompanyConfig, source: LocalDocsSource, cache_dir: Path) -> None:
        """Nothing to download: the files are already local."""

    def records(
        self, company: CompanyConfig, source: LocalDocsSource, cache_dir: Path
    ) -> Iterator[CanonicalRecord]:
        folder = company.resolve(source.path)
        if not folder.is_dir():
            raise SourceUnavailable(f"folder {folder} does not exist")
        for path in sorted(folder.rglob("*")):
            if path.suffix.lower() not in SUFFIXES or not path.is_file():
                continue
            rel = path.relative_to(folder).as_posix()
            body = path.read_text(errors="replace")
            yield Document(
                uid=f"{self.name}:{company.slug}:{rel}",
                source=self.name,
                path=rel,
                title=doc_title(path, body),
                body=body,
                updated_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
            )
