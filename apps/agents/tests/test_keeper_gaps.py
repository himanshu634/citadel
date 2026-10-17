"""Gaps from Ask turns and thumbs (agents/keeper/gaps.py), on the in-memory ledger."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from agents.keeper.gaps import note_feedback, note_trace
from agents.keeper.store import MemoryKeeperStore
from agents.traces import Trace

NOW = "2026-10-17T10:00:00Z"
LATER = "2026-10-17T10:05:00Z"


def trace(id="t1", question="Who owns Billing?", **kw) -> Trace:
    base = {
        "id": id,
        "at": datetime(2026, 10, 17, 10, tzinfo=UTC),
        "slug": "synthetic",
        "via": "api",
        "thread_id": "th",
        "question": question,
        "stop": "tool_use",
        "text": "An answer [1].",
        "sources": 1,
        "cited": ["pr:1"],
    }
    return Trace.model_validate({**base, **kw})


@pytest.fixture
def store():
    return MemoryKeeperStore("synthetic")


def test_failed_turn_opens_gap(store):
    t = trace(text=None, sources=0, cited=[], stop="error")
    uid = note_trace(store, t, NOW)
    [gap] = store.gaps.values()
    assert uid == gap.uid and gap.kind == "failed_question"
    assert gap.trace_ids == [t.id] and gap.text == "Who owns Billing?"
    assert gap.norm == "who owns billing" and gap.created_at == NOW


def test_zero_source_answer_opens_gap(store):
    t = trace(text="x", sources=0, cited=[])
    assert note_trace(store, t, NOW) is not None
    assert [g.kind for g in store.gaps.values()] == ["failed_question"]


def test_an_interview_turn_with_nothing_to_ask_opens_no_gap(store):
    """ "Ask me questions" with no open gaps answers without a source; that is not a failure."""
    told = trace(question="Ask me questions.", text="No open questions.", sources=0, cited=[],
                 tools=["open_gaps"])  # fmt: skip
    assert note_trace(store, told, NOW) is None
    died = told.model_copy(update={"text": None, "stop": "error"})
    assert note_trace(store, died, NOW) is not None


def test_good_turn_no_gap(store):
    assert note_trace(store, trace(sources=2, cited=["pr:1", "pr:2"]), NOW) is None
    assert store.gaps == {}


def test_same_question_differently_cased(store):
    first = note_trace(store, trace("t1", "Who owns Billing?", text=None, sources=0), NOW)
    second = note_trace(store, trace("t2", "who owns billing", text=None, sources=0), LATER)
    assert first == second
    [gap] = store.gaps.values()
    assert gap.count == 2 and gap.trace_ids == ["t1", "t2"]


def test_about_is_the_cited_uids(store):
    note_trace(store, trace(text="x", sources=0, cited=["pr:9"]), NOW)
    [gap] = store.gaps.values()
    assert gap.about == ["pr:9"]


def test_store_failure_is_swallowed(capsys):
    class Broken:
        slug = "synthetic"

        def write(self, *_a, **_k):
            raise RuntimeError("FalkorDB is down")

    t = trace(text=None, sources=0)
    assert note_trace(Broken(), t, NOW) is None
    assert note_feedback(Broken(), t, "down", NOW) is None
    assert "FalkorDB is down" in capsys.readouterr().err


def test_thumbs_down_opens_gap_and_other_ratings_do_not(store):
    t = trace()
    assert note_feedback(store, t, "up", NOW) is None
    assert note_feedback(store, t, None, NOW) is None
    assert store.gaps == {}
    uid = note_feedback(store, t, "down", NOW)
    [gap] = store.gaps.values()
    assert uid == gap.uid and gap.kind == "thumbs_down" and gap.trace_ids == [t.id]
    assert gap.about == ["pr:1"]


def test_thumbs_down_twice_is_one_gap(store):
    note_feedback(store, trace("t1"), "down", NOW)
    note_feedback(store, trace("t2", "WHO owns billing??"), "down", LATER)
    [gap] = store.gaps.values()
    assert gap.count == 2


def test_failed_and_thumbs_down_are_separate_gaps(store):
    note_trace(store, trace(text=None, sources=0), NOW)
    note_feedback(store, trace(text=None, sources=0), "down", NOW)
    assert sorted(g.kind for g in store.gaps.values()) == ["failed_question", "thumbs_down"]


@pytest.mark.parametrize("question", ["?", "...", "  ?! ", ""])
def test_a_question_with_nothing_left_after_normalising_opens_no_gap(store, question):
    t = trace(question=question, text=None, sources=0)
    assert note_trace(store, t, NOW) is None
    assert note_feedback(store, t, "down", NOW) is None
    assert store.gaps == {}
