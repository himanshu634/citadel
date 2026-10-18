"""local_docs: a folder of markdown / text files -> Document records. No cache, no network."""

from __future__ import annotations

from pathlib import Path

import pytest
from brain import config
from brain.adapters import REGISTRY
from brain.adapters.local_docs import LocalDocsAdapter
from brain.canonical import Document
from brain.config import CompanyConfig

NO_CACHE = Path("/nonexistent")  # the adapter reads only its folder


def company(tmp_path, monkeypatch, folders: list[str]) -> CompanyConfig:
    """A company whose sources are `folders` (repo-root relative, under tmp_path)."""
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    return CompanyConfig.model_validate(
        {
            "slug": "docs_test",
            "name": "Docs test",
            "data_permission": "own",
            "window": {"since": "2026-01-01"},
            "sources": [{"type": "local_docs", "path": f} for f in folders],
        }
    )


def write(tmp_path, folder: str, name: str, text: str) -> None:
    path = tmp_path / folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def docs(cfg: CompanyConfig) -> list[Document]:
    adapter = LocalDocsAdapter()
    return [d for s in cfg.sources for d in adapter.records(cfg, s, NO_CACHE)]


def test_registered():
    assert isinstance(REGISTRY["local_docs"], LocalDocsAdapter)


def test_two_folders_with_the_same_file_name_are_two_documents(tmp_path, monkeypatch):
    """Both folders hold a README.md: two Document uids, each naming its source folder, so the
    second folder's load cannot overwrite the first's node."""
    cfg = company(tmp_path, monkeypatch, ["inbox/design", "inbox/runbooks"])
    write(tmp_path, "inbox/design", "README.md", "# Design\n\nHow it is built.")
    write(tmp_path, "inbox/runbooks", "README.md", "# Runbooks\n\nWhat to do at 3am.")
    found = docs(cfg)
    assert [d.title for d in found] == ["Design", "Runbooks"]
    assert len({d.uid for d in found}) == 2
    assert all(d.path == "README.md" for d in found)
    assert "inbox/design" in found[0].uid and "inbox/runbooks" in found[1].uid


def test_title_from_the_first_heading_else_the_file_name(tmp_path, monkeypatch):
    cfg = company(tmp_path, monkeypatch, ["inbox/docs"])
    write(tmp_path, "inbox/docs", "adr/001-keys.md", "# Rotate keys\n\nEvery 90 days.")
    write(tmp_path, "inbox/docs", "on_call-guide.txt", "No heading here.")
    by_path = {d.path: d for d in docs(cfg)}
    assert by_path["adr/001-keys.md"].title == "Rotate keys"
    assert by_path["on_call-guide.txt"].title == "on call guide"
    assert by_path["adr/001-keys.md"].body.startswith("# Rotate keys")


def test_only_markdown_and_text_files_are_read(tmp_path, monkeypatch):
    cfg = company(tmp_path, monkeypatch, ["inbox/docs"])
    write(tmp_path, "inbox/docs", "notes.md", "# Notes")
    write(tmp_path, "inbox/docs", "diagram.png", "not text")
    write(tmp_path, "inbox/docs", "data.json", "{}")
    assert [d.path for d in docs(cfg)] == ["notes.md"]


def test_missing_folder_is_unavailable(tmp_path, monkeypatch):
    from brain.adapters import SourceUnavailable

    cfg = company(tmp_path, monkeypatch, ["inbox/missing"])
    with pytest.raises(SourceUnavailable):
        docs(cfg)
