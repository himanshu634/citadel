"""The Archivist's fixed rules: request key, scope, the checks on a find, and recall."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from agents.archivist import rules
from agents.keeper.model import ArchiveRequest
from agents.keeper.store import MemoryKeeperStore
from brain.archive.backends import Candidate, Fetched

T1 = "2026-10-17T10:00:00Z"
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
UID = "github:acme/widgets:issue:12"
TEXT = "We dropped sqlite because writers\nblocked each other under load in 2023."
QUOTE = "dropped sqlite because writers blocked each other"


def _fetched(uid=UID, text=TEXT) -> Fetched:
    c = Candidate(
        id="github:acme/widgets#12",
        uid=uid,
        ref="github:acme/widgets#12",
        source_key="github:acme/widgets",
        kind="issue",
        title="Drop sqlite",
        url="https://github.com/acme/widgets/issues/12",
    )
    return Fetched(candidate=c, text=text, records=[], refs=[])


def _find(**kw):
    base = {
        "uid": UID,
        "why": "it states the reason",
        "quote": QUOTE,
        "verdict": "holds",
        "evidence": ["system:db"],
        "superseded_by": None,
    }
    return SimpleNamespace(**{**base, **kw})


def _request(kind="topic", refs=None) -> ArchiveRequest:
    return ArchiveRequest(
        uid="archive:aaaaaaaaaaaa",
        kind=kind,
        text="why sqlite",
        refs=refs or [],
        asked_by="ask",
        norm="x",
        created_at=T1,
        updated_at=T1,
    )


def in_brain(uid):
    return {"uid": uid} if uid == "system:db" else None


def test_norm_of_refs_is_sorted_and_exact():
    n = rules.norm("reference", "ignored", ["Acme/Widgets#12", " acme/widgets#3 "])
    assert n == "acme/widgets#12,acme/widgets#3"


def test_norm_of_text_drops_stop_words_and_sorts():
    assert rules.norm("topic", "Why did we drop SQLite?", []) == "drop sqlite"
    assert rules.norm("topic", "sqlite DROP", []) == "drop sqlite"
    assert rules.norm("reference", "Why did we drop SQLite?", []) == "drop sqlite"


class _Backend:
    def __init__(self, repo):
        self.repo = repo

    def parse_ref(self, ref):
        return ref if ref.startswith(self.repo) else None


def test_out_of_scope_repo():
    backends = {"github:acme/widgets": _Backend("acme/widgets")}
    assert rules.check_scope(["acme/widgets#3"], backends) is None
    assert rules.check_scope(["acme/widgets#3", "other/repo#1"], backends) == "out_of_scope"
    assert rules.check_scope(["other/repo#1"], {}) == "out_of_scope"


def test_valid_find_passes_and_whitespace_is_normalised():
    assert rules.check_find(_find(), _fetched(), _request(), in_brain) is None


def test_not_fetched_this_run():
    reason = rules.check_find(_find(), None, _request(), in_brain)
    assert reason and "not fetched" in reason
    other = _fetched(uid="github:acme/widgets:issue:99")
    assert "not fetched" in rules.check_find(_find(), other, _request(), in_brain)


def test_why_must_not_be_empty():
    assert "why" in rules.check_find(_find(why="  "), _fetched(), _request(), in_brain)


def test_quote_must_be_substring():
    assert "quote" in rules.check_find(_find(quote="x" * 19), _fetched(), _request(), in_brain)
    absent = _find(quote="a long quote nobody wrote")
    reason = rules.check_find(absent, _fetched(), _request(), in_brain)
    assert reason and "quote" in reason


def test_exact_ref_skips_quote():
    request = _request("reference", [UID])
    assert rules.check_find(_find(quote=""), _fetched(), request, in_brain) is None
    by_ref = _request("reference", ["GitHub:acme/widgets#12"])
    assert rules.check_find(_find(quote=""), _fetched(), by_ref, in_brain) is None
    other = _request("reference", ["github:acme/widgets#99"])
    assert "quote" in rules.check_find(_find(quote=""), _fetched(), other, in_brain)
    assert "why" in rules.check_find(_find(quote="", why=""), _fetched(), request, in_brain)


def test_evidence_must_exist_in_brain():
    assert "evidence" in rules.check_find(_find(evidence=[]), _fetched(), _request(), in_brain)
    reason = rules.check_find(
        _find(evidence=["system:db", "system:x"]), _fetched(), _request(), in_brain
    )
    assert reason and "system:x" in reason


def _answered(store, uid, norm="n", asked_by="ask", outcome="found", partial=False, now=T1):
    params = {
        "uid": uid, "kind": "topic", "text": "t", "asked_by": asked_by, "norm": norm, "now": now,
    }  # fmt: skip
    store.write("ledger/archive_open_request", "citadel_archivist", params)
    store.write(
        "ledger/archive_set_request",
        "citadel_archivist",
        {"uid": uid, "from": ["open"], "to": "answered", "outcome": outcome,
         "partial": partial, "now": now},
    )  # fmt: skip


def test_recall_serves_a_recent_answer():
    store = MemoryKeeperStore("t")
    _answered(store, "archive:a")
    got = rules.recall(store, "n", "ask", NOW)
    assert got is not None and got.uid == "archive:a"
    assert rules.recall(store, "other", "ask", NOW) is None


def test_recall_forgets_after_memory_days():
    store = MemoryKeeperStore("t")
    _answered(store, "archive:a", now="2026-09-01T10:00:00Z")  # 46 days before NOW
    assert rules.recall(store, "n", "ask", NOW) is None
    assert rules.recall(store, "n", "ask", "2026-09-20T10:00:00Z") is not None


def test_recall_ignores_partial():
    store = MemoryKeeperStore("t")
    _answered(store, "archive:a", partial=True)
    assert rules.recall(store, "n", "ask", NOW) is None


def test_ask_nothing_found_does_not_serve_keeper():
    store = MemoryKeeperStore("t")
    _answered(store, "archive:a", outcome="nothing_found")
    assert rules.recall(store, "n", "keeper", NOW) is None
    assert rules.recall(store, "n", "ask", NOW) is not None
    _answered(store, "archive:b", asked_by="keeper", outcome="nothing_found", now=T1)
    assert rules.recall(store, "n", "keeper", NOW).uid == "archive:b"


@pytest.mark.parametrize("asked_by", ["ask", "keeper"])
def test_ask_found_serves_both_tiers(asked_by):
    store = MemoryKeeperStore("t")
    _answered(store, "archive:a", outcome="found")
    assert rules.recall(store, "n", asked_by, NOW) is not None
