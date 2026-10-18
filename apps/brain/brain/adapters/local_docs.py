"""Adapter for a folder of markdown / text files a company has published.

Why: design docs, ADRs and runbooks often live outside the code host. Dropping them in a folder
turns each file into a Document node that agents can search and cite.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from brain.adapters.base import FolderAdapter, first_heading
from brain.canonical import CanonicalRecord, Document
from brain.config import CompanyConfig, PathSource

SUFFIXES = {".md", ".markdown", ".txt"}


def doc_title(path: Path, body: str) -> str:
    """First markdown heading, else the file name."""
    heading = first_heading(body)
    if heading is not None:
        return heading
    return path.stem.replace("-", " ").replace("_", " ")


class LocalDocsSource(PathSource):
    type: Literal["local_docs"]


class LocalDocsAdapter(FolderAdapter):
    name = "local_docs"
    source_model = LocalDocsSource

    def records(
        self, company: CompanyConfig, source: LocalDocsSource, cache_dir: Path
    ) -> Iterator[CanonicalRecord]:
        folder = self.folder(company, source)
        # The uid names the source folder: two folders may both hold a README.md.
        prefix = f"{self.name}:{company.slug}:{source.path.as_posix()}"
        for path in sorted(folder.rglob("*")):
            if path.suffix.lower() not in SUFFIXES or not path.is_file():
                continue
            rel = path.relative_to(folder).as_posix()
            body = path.read_text(errors="replace")
            yield Document(
                uid=f"{prefix}:{rel}",
                source=self.name,
                path=rel,
                title=doc_title(path, body),
                body=body,
                updated_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
            )
