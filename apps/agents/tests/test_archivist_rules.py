"""The Archivist's fixed rules: request key, scope, the checks on a find, and recall."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from agents.archivist import rules
from agents.keeper.model import ArchiveRequest
from agents.keeper.store import MemoryKeeperStore
from brain.adapters.github import GithubSource
from brain.adapters.linear import LinearSource
from brain.adapters.linear import client as lc
from brain.archive.backends import Candidate, Fetched, GithubBackend, LinearBackend
from brain.config import CompanyConfig

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


# --- rule 13: an exact ref must resolve to the item (real backends' parse_ref, no network) ----

LIN_UUID = "0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d"
LIN_UID = f"linear:issue:{LIN_UUID}"


@pytest.fixture
def backends(tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "token", lambda: "test")
    (tmp_path / "meta.json").write_text(
        '{"nameWithOwner": "acme/widgets", "url": "https://github.com/acme/widgets",'
        ' "isPrivate": false, "defaultBranch": "main"}'
    )
    cfg = CompanyConfig.model_validate(
        {
            "slug": "archtest_rules",
            "name": "x",
            "data_permission": "synthetic",
            "window": {"since": "2026-01-01"},
            "sources": [
                {"type": "github", "repo": "acme/widgets"},
                {"type": "linear", "workspace": "acme", "teams": ["ENG"]},
            ],
        }
    )
    client = lc.LinearClient(log=lambda m: None, transport=httpx.MockTransport(lambda r: None))
    gh = GithubBackend(
        cfg, GithubSource(type="github", repo="acme/widgets"), tmp_path, lambda p: None
    )
    lin = LinearBackend(cfg, LinearSource(type="linear", workspace="acme", teams=["ENG"]),
                        lambda p: None, client=client)  # fmt: skip
    return {gh.key: gh, lin.key: lin}


def _exact(backends, ref, fetched, ids):
    request = _request("reference", [ref])
    find = _find(quote="", uid=fetched.candidate.uid)
    return rules.check_find(
        find, fetched, request, in_brain, ids=ids, resolve=rules.resolver(backends)
    )


def test_exact_ref_hash_number_resolves_for_github(backends):
    f = _fetched()  # github:acme/widgets#12
    assert _exact(backends, "#12", f, {"github:acme/widgets#12", UID}) is None
    assert _exact(backends, "acme/widgets#12", f, {"github:acme/widgets#12"}) is None
    assert _exact(backends, "#13", f, {"github:acme/widgets#12"}) is not None


def test_exact_ref_url_with_trailing_slash(backends):
    f = _fetched()
    url = "https://github.com/acme/widgets/issues/12/"
    assert _exact(backends, url, f, {"github:acme/widgets#12"}) is None
    lin = "https://linear.app/acme/issue/ENG-12/"
    assert _exact(backends, lin, _linear(), {"ENG-12", LIN_UID}) is None


def _linear() -> Fetched:
    c = Candidate(id=LIN_UID, uid=LIN_UID, ref=LIN_UID, source_key="linear:acme", kind="ticket",
                  title="t")  # fmt: skip
    return Fetched(candidate=c, text=TEXT, records=[], refs=[])


def test_exact_ref_linear_key_fetched_by_key(backends):
    # the session fetched it as "ENG-12": the candidate carries the uuid uid, the key is an alias
    assert _exact(backends, "ENG-12", _linear(), {"ENG-12", LIN_UID}) is None
    assert _exact(backends, "ENG-13", _linear(), {"ENG-12", LIN_UID}) is not None


def test_exact_ref_bare_uuid(backends):
    assert _exact(backends, LIN_UUID.upper(), _linear(), {LIN_UID}) is None


def test_a_key_needs_the_session_to_have_seen_it(backends):
    # the candidate carries only the uuid uid: without the alias ids, "ENG-12" is no match
    assert "quote" in _exact(backends, "ENG-12", _linear(), set())


# --- norm is never empty ----------------------------------------------------------------------


def test_norm_of_only_stop_words_is_not_empty():
    assert rules.norm("topic", "why?", []) == "why?"
    assert rules.norm("topic", "why?", []) != rules.norm("topic", "how?", [])
    assert rules.norm("topic", "  Why   ?? ", []) == "why ??"


def test_norm_of_non_ascii_text():
    n = rules.norm("topic", "为什么放弃 SQLite", [])
    assert n and "sqlite" in n
    assert rules.norm("topic", "Почему SQLite", []) != rules.norm("topic", "为什么放弃", [])


def test_store_rejects_an_empty_norm():
    store = MemoryKeeperStore("t")
    with pytest.raises(ValueError):
        store.write(
            "ledger/archive_open_request",
            "citadel_archivist",
            {"uid": "archive:x", "kind": "topic", "text": "t", "asked_by": "ask", "norm": "",
             "now": T1},
        )  # fmt: skip


# --- superseded_by ----------------------------------------------------------------------------


def test_superseded_needs_superseded_by_in_the_brain():
    f = _fetched()
    bare = _find(verdict="superseded")
    assert "superseded_by" in rules.check_find(bare, f, _request(), in_brain)
    gone = _find(verdict="superseded", superseded_by="system:gone")
    assert "system:gone" in rules.check_find(gone, f, _request(), in_brain)
    ok = _find(verdict="superseded", superseded_by="system:db")
    assert rules.check_find(ok, f, _request(), in_brain) is None


@pytest.mark.parametrize("verdict", ["holds", "conflicts"])
def test_other_verdicts_must_not_name_superseded_by(verdict):
    bad = _find(verdict=verdict, superseded_by="system:db")
    reason = rules.check_find(bad, _fetched(), _request(), in_brain)
    assert reason and "superseded_by" in reason
