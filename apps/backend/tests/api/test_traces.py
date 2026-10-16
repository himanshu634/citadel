"""Traces through the API: every Ask turn is kept, rated with a thumbs and summarised
(scripted Claude, fake tools, traces in a throwaway data/)."""

from __future__ import annotations

import pytest
from agents.testing import FakeClient, reply, settings, submit, tool_use  # noqa: F401
from agents.traces import TraceStore

from .conftest import write
from .test_ask import frames, make_client


@pytest.fixture
def company(api_root):
    write(api_root, "synthetic", name="Synthetic Co")
    write(api_root, "other", name="Other Co")
    return "synthetic"


def ask(client, slug="synthetic", question="Why JWT?") -> dict:
    r = client.post(f"/api/companies/{slug}/ask", json={"question": question})
    return frames(r.text)[-1][1]


def test_an_ask_keeps_one_trace_and_names_it_in_the_answer(company, runner):
    claude = FakeClient(
        reply(tool_use("t1", "related_work_items", {"text": "boom"})),
        reply(submit("t2", "Made up [1].", ["pr:999"])),
        reply(submit("t3", "Nothing found.", [])),
    )
    answer = ask(make_client(runner, claude))
    [t] = TraceStore(company).read()
    assert answer["trace_id"] == t.id
    assert (t.via, t.question, t.thread_id) == ("api", "Why JWT?", answer["thread_id"])
    assert t.tools == ["related_work_items"] and len(t.tool_errors) == 1
    assert len(t.rejected) == 1 and t.sources == 0 and t.usage.total == 3 * 190
    assert t.ms >= 0


def test_a_failed_run_is_kept_as_an_error_trace(company, runner):
    class NoKey:
        def __init__(self):
            self.beta = self
            self.messages = self

        def stream(self, **_):
            raise TypeError("Could not resolve authentication method.")

    r = make_client(runner, NoKey()).post(
        f"/api/companies/{company}/ask", json={"question": "Why?"}
    )
    assert frames(r.text)[-1][0] == "error"
    [t] = TraceStore(company).read()
    assert t.stop == "error" and t.error and t.text is None


def test_a_trace_that_could_not_be_written_has_no_id(company, runner, monkeypatch):
    monkeypatch.setattr(TraceStore, "add", lambda self, trace: False)
    answer = ask(make_client(runner, FakeClient(reply(submit("t1", "Fine.", [])))))
    assert answer["trace_id"] is None and answer["text"] == "Fine."


def test_thumbs_are_stored_changed_and_taken_back(company, runner):
    client = make_client(runner, FakeClient(reply(submit("t1", "Fine.", []))))
    trace_id = ask(client)["trace_id"]
    url = f"/api/companies/{company}/traces/{trace_id}/feedback"

    r = client.post(url, json={"rating": "down", "note": "wrong team"})
    assert r.status_code == 200
    assert r.json() == {"trace_id": trace_id, "rating": "down", "note": "wrong team"}
    assert client.post(url, json={"rating": None}).json()["rating"] is None
    [t] = TraceStore(company).read()
    assert t.feedback.rating is None


def test_feedback_for_an_unknown_or_foreign_trace_is_404(company, runner):
    client = make_client(runner, FakeClient(reply(submit("t1", "Fine.", []))))
    trace_id = ask(client)["trace_id"]
    other = client.post(f"/api/companies/other/traces/{trace_id}/feedback", json={"rating": "up"})
    assert other.status_code == 404
    missing = client.post(f"/api/companies/{company}/traces/nope/feedback", json={"rating": "up"})
    assert missing.status_code == 404
    bad = client.post(
        f"/api/companies/{company}/traces/{trace_id}/feedback", json={"rating": "meh"}
    )
    assert bad.status_code == 422
    path = client.post(f"/api/companies/{company}/traces/a.b/feedback", json={"rating": "up"})
    assert path.status_code == 422
    assert (
        client.post("/api/companies/nope/traces/x/feedback", json={"rating": "up"}).status_code
        == 404
    )


def test_summary_over_a_window(company, runner):
    claude = FakeClient(reply(submit("t1", "Fine.", [])), reply(submit("t2", "Also.", [])))
    client = make_client(runner, claude)
    trace_id = ask(client)["trace_id"]
    ask(client, question="Again?")
    client.post(f"/api/companies/{company}/traces/{trace_id}/feedback", json={"rating": "up"})

    r = client.get(f"/api/companies/{company}/traces/summary", params={"days": 1})
    assert r.status_code == 200
    s = r.json()
    assert (s["turns"], s["answered"]) == (2, 2)
    assert s["rates"]["zero_source"] == 1.0 and s["rates"]["no_answer"] == 0.0
    assert s["thumbs"] == {"up": 1, "down": 0}
    assert s["latency_ms"]["p50"] is not None and s["tokens"]["p95"] == 190

    empty = client.get("/api/companies/other/traces/summary").json()
    assert empty["turns"] == 0 and empty["rates"]["nudge"] is None
    assert client.get(f"/api/companies/{company}/traces/summary?days=0").status_code == 422


def test_a_thumbs_down_leaves_a_thumbs_down_gap(company, runner):
    from agents.keeper.store import MemoryKeeperStore

    ledger = MemoryKeeperStore(company)
    client = make_client(runner, FakeClient(reply(submit("t1", "Fine.", []))))
    client.app.state.asker.ledger = lambda slug: ledger
    trace_id = ask(client)["trace_id"]
    ledger.gaps.clear()  # the zero-source answer itself opened a failed_question gap
    url = f"/api/companies/{company}/traces/{trace_id}/feedback"

    assert client.post(url, json={"rating": "up"}).status_code == 200
    assert ledger.gaps == {}
    assert client.post(url, json={"rating": "down"}).status_code == 200
    [gap] = ledger.gaps.values()
    assert (gap.kind, gap.trace_ids, gap.text) == ("thumbs_down", [trace_id], "Why JWT?")


def test_an_unanswered_ask_leaves_a_failed_question_gap(company, runner):
    from agents.keeper.store import MemoryKeeperStore

    ledger = MemoryKeeperStore(company)
    client = make_client(runner, FakeClient(reply(submit("t1", "Nothing.", []))))
    client.app.state.asker.ledger = lambda slug: ledger
    trace_id = ask(client)["trace_id"]
    [gap] = ledger.gaps.values()
    assert (gap.kind, gap.trace_ids) == ("failed_question", [trace_id])


def test_a_broken_ledger_does_not_fail_the_answer_or_the_rating(company, runner):
    class Broken:
        def write(self, *_a, **_k):
            raise RuntimeError("down")

    client = make_client(runner, FakeClient(reply(submit("t1", "Nothing.", []))))
    client.app.state.asker.ledger = lambda slug: Broken()
    answer = ask(client)
    assert answer["text"] == "Nothing."
    url = f"/api/companies/{company}/traces/{answer['trace_id']}/feedback"
    assert client.post(url, json={"rating": "down"}).status_code == 200


def test_the_answer_is_sent_before_the_gap_is_written(company, runner):
    import threading
    import time

    gate = threading.Event()
    wrote = []

    class Slow:
        def write(self, *_a, **_k):
            wrote.append("write")
            gate.wait(5)  # a ledger that hangs
            return [{"uid": "gap:x"}]

    client = make_client(runner, FakeClient(reply(submit("t1", "Nothing.", []))))
    client.app.state.asker.ledger = lambda slug: Slow()
    started = time.perf_counter()
    try:
        answer = ask(client)
        took = time.perf_counter() - started
    finally:
        gate.set()
    assert answer["text"] == "Nothing." and answer["trace_id"]
    assert took < 2  # the stream ended while the write was still blocked
