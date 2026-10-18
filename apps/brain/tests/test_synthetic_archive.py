"""The synthetic company's archive: items older than the window, for the Archivist's demo."""

from __future__ import annotations

import json
from datetime import date

from brain.archive.backends import JsonlArchiveBackend
from brain.testing import SYNTHETIC

ARCHIVE = SYNTHETIC / "archive"
WINDOW_START = "2026-01-01"


def rows(folder, name):
    path = folder / name
    return [json.loads(line) for line in path.open()] if path.exists() else []


def test_synthetic_archive_is_pre_window_and_referenced():
    items = rows(ARCHIVE, "work_items.jsonl")
    docs = rows(ARCHIVE, "documents.jsonl")
    assert len(items) + len(docs) >= 6
    assert all(i["created_at"] < WINDOW_START for i in items)
    assert all(d["updated_at"] < WINDOW_START for d in docs)
    assert "Old auth system design" in {d["title"] for d in docs}
    windowed = rows(SYNTHETIC, "work_items.jsonl")
    windowed_uids = {
        r["uid"] for name in ("work_items", "documents") for r in rows(SYNTHETIC, f"{name}.jsonl")
    }
    assert not windowed_uids & {r["uid"] for r in items + docs}
    assert any("synthetic:issue:900" in w.get("unresolved_refs", []) for w in windowed)
    assert any("decisive proof is in #900" in w["body"] for w in windowed)


def test_synthetic_archive_holds_a_decision_a_windowed_item_overturns():
    old = next(i for i in rows(ARCHIVE, "work_items.jsonl") if "24h session expiry" in i["title"])
    new = next(
        w for w in rows(SYNTHETIC, "work_items.jsonl") if "session expiry to 1h" in w["title"]
    )
    assert old["created_at"] < WINDOW_START <= new["created_at"]


def test_jsonl_archive_backend_finds_and_fetches_the_decision():
    backend = JsonlArchiveBackend("synthetic", ARCHIVE)
    hits = backend.search("sessions JWT", date.fromisoformat(WINDOW_START))
    assert "synthetic:issue:900" in {h.uid for h in hits}
    fetched = backend.fetch("synthetic:issue:900")
    comments = [r for r in fetched.records if r.__class__.__name__ == "Comment"]
    assert len(comments) == 3
    assert any("decision" in c.body.lower() for c in comments)


def test_jsonl_archive_backend_parses_a_number_and_a_url():
    backend = JsonlArchiveBackend("synthetic", ARCHIVE)
    assert backend.parse_ref("synthetic:issue:900") == "synthetic:issue:900"
    assert backend.parse_ref("#900") == "synthetic:issue:900"
    assert backend.parse_ref(" #903 ") == "synthetic:pr:903"  # any kind with that number
    url = "https://example.com/synthetic/app/issues/901"
    assert backend.parse_ref(url) == "synthetic:issue:901"
    assert backend.parse_ref("#999") is None
    assert backend.parse_ref("https://example.com/synthetic/app/issues/999") is None
    assert backend.parse_ref("auth") is None
    assert backend.fetch(backend.parse_ref("#900")).candidate.uid == "synthetic:issue:900"
