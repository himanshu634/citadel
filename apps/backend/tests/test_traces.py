"""Online traces (brain/agents/traces.py) and the thumbs-down drafts (evals/drafts.py), with a
scripted Claude: no API calls, no database."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
import yaml
from brain import cli, config, registry
from brain.agents import ask as agent
from brain.agents.history import MemoryChatStore
from brain.agents.traces import Feedback, Trace, TraceStore, new_trace, summarize, window
from conftest import synthetic_company
from evals import cases, drafts
from langgraph.checkpoint.memory import InMemorySaver
from tests.test_agent import TOOLSET, FakeClient, reply, settings, submit, text, tool_use  # noqa: F401
from typer.testing import CliRunner

NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A throwaway repo root holding companies/synthetic.yaml; traces land in its data/."""
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    (tmp_path / "companies").mkdir()
    registry.write_new(synthetic_company("synthetic"))
    return tmp_path


def trace(i: int, **kw) -> Trace:
    base = {
        "id": f"t{i}",
        "at": NOW - timedelta(minutes=60 - i),
        "slug": "synthetic",
        "via": "api",
        "thread_id": f"th{i}",
        "question": f"q{i}",
        "stop": "tool_use",
        "text": "An answer [1].",
        "sources": 1,
        "cited": ["pr:1"],
        "ms": 1000 * i,
        "usage": {"total": 100 * i},
    }
    return Trace.model_validate({**base, **kw})


# --- what a trace holds -----------------------------------------------------------------------


def test_a_turn_trace_counts_errors_rejections_nudges_and_tokens(root):
    client = FakeClient(
        reply(
            tool_use("t1", "related_work_items", {"text": "boom"}),
            tool_use("t2", "related_work_items", {"text": "jwt"}),
        ),
        reply(text("It was for load."), stop="end_turn"),  # plain text: nudged
        reply(submit("t3", "Made up [1].", ["pr:999"])),  # rejected: never seen
        reply(submit("t4", "JWT [1].", ["pr:1"], ["person:a", "pr:1"])),
    )
    answer, steps = agent.ask_traced("synthetic", "Why JWT?", client=client, toolset=TOOLSET)
    assert answer.nudges == 1

    t = new_trace("synthetic", "Why JWT?", answer.thread_id, via="cli", steps=steps, ms=42,
                  answer=answer)  # fmt: skip
    assert t.tools == ["related_work_items", "related_work_items"]
    assert t.tool_errors == ["related_work_items: related_work_items failed: RuntimeError: "
                             "query failed"]  # fmt: skip
    assert len(t.rejected) == 1 and "pr:999" in t.rejected[0]
    assert (t.nudges, t.stop, t.model, t.effort) == (1, "tool_use", "claude-haiku-5-5", "medium")
    # Four calls of 100 in (80 of them cache reads) and 10 out each.
    assert t.usage.model_dump() == {
        "input": 400, "cache_read": 320, "cache_write": 0, "output": 40, "total": 760
    }  # fmt: skip
    assert (t.sources, t.cited, t.path, t.ms) == (1, ["pr:1"], ["person:a", "pr:1"], 42)
    assert t.answered and t.text == "JWT [1]."
    # Asking never records by itself: only the CLI and the Ask API keep traces.
    assert not (root / "data").exists()


def test_a_run_that_raised_is_an_error_trace():
    t = new_trace("synthetic", "Why?", "th", via="api", steps=[], ms=5, error="Overloaded")
    assert (t.stop, t.error, t.answered, t.usage.total) == ("error", "Overloaded", False, 0)


# --- the store --------------------------------------------------------------------------------


def test_store_appends_and_folds_the_latest_thumbs(tmp_path):
    store = TraceStore("synthetic", root=tmp_path)
    assert store.read() == [] and store.rate("t1", "up") is None
    assert store.add(trace(1)) and store.add(trace(2))
    assert store.rate("t1", "down", "  wrong person  ").feedback.note == "wrong person"
    store.rate("t1", "up")  # changed their mind
    store.rate("t2", "down")
    store.rate("t2", None)  # took it back
    with store.path.open("a") as fh:
        fh.write('{"kind": "turn", "id": "half')  # a write cut off by a crash
    got = {t.id: t.feedback for t in store.read()}
    assert got["t1"].rating == "up" and got["t1"].note is None
    assert got["t2"].rating is None
    lines = [json.loads(x) for x in store.path.read_text().splitlines()[:2]]
    assert [x["kind"] for x in lines] == ["turn", "turn"] and "feedback" not in lines[0]

    assert [t.id for t in store.read(since=NOW - timedelta(minutes=58.5))] == ["t2"]
    assert store.forget() and not store.path.exists() and not store.forget()


def test_one_company_cannot_rate_another_companys_trace(tmp_path):
    TraceStore("synthetic", root=tmp_path).add(trace(1))
    assert TraceStore("other", root=tmp_path).rate("t1", "down") is None


# --- the summary ------------------------------------------------------------------------------


def test_summary_rates_percentiles_and_thumbs():
    up = Feedback(rating="up", at=NOW)
    down = Feedback(rating="down", at=NOW)
    traces = [
        trace(1, feedback=up),
        trace(2, sources=0, cited=[], nudges=1),  # answered with no sources, after a nudge
        trace(3, stop="no_answer", text=None, sources=0, rejected=["bad uid"], feedback=down),
        trace(4, stop="step_limit", text=None, sources=0, tool_errors=["x: failed"]),
        trace(5, stop="stopped", text=None, sources=0),
        trace(6, stop="error", text=None, sources=0, error="Overloaded", usage={}),
        trace(7, stop="refusal", text=None, sources=0),
        trace(8, at=NOW - timedelta(days=9)),  # outside the window
    ]
    since, until = window(7, now=NOW)
    s = summarize(traces, since, until)
    assert (s.turns, s.answered) == (7, 2)
    r = s.rates
    assert r.no_answer == r.step_limit == r.refusal == r.stopped == r.error == round(1 / 7, 4)
    assert r.nudge == r.rejected_submit == r.tool_error == round(1 / 7, 4)
    assert r.max_tokens == 0
    assert r.zero_source == 0.5  # of the two answered turns
    assert s.stops == {"error": 1, "no_answer": 1, "refusal": 1, "step_limit": 1, "stopped": 1,
                       "tool_use": 2}  # fmt: skip
    assert (s.latency_ms.p50, s.latency_ms.p95) == (4000, 7000)  # nearest rank over 1..7 s
    assert (s.tokens.p50, s.tokens.p95) == (300, 700)  # the error turn has no tokens
    assert (s.thumbs.up, s.thumbs.down) == (1, 1)


def test_an_empty_window_has_no_rates():
    since, until = window(7, now=NOW)
    s = summarize([], since, until)
    assert s.turns == 0 and s.rates.no_answer is None and s.latency_ms.p50 is None


# --- the CLI ----------------------------------------------------------------------------------


def test_cli_ask_keeps_a_trace_and_offline_does_not(root, monkeypatch):
    monkeypatch.setattr("brain.db.checkpointer", lambda slug: InMemorySaver())
    history = MemoryChatStore()
    monkeypatch.setattr("brain.agents.history.GraphChatStore", lambda slug: history)
    monkeypatch.setattr("brain.llm.client", lambda: FakeClient(reply(submit("t1", "None.", []))))
    answer = cli._run_ask("synthetic", "Who knows Auth?", None)
    offline = FakeClient(reply(submit("t1", "Scripted.", [])))
    cli._run_ask("synthetic", "Which systems?", answer.thread_id, offline)

    [t] = TraceStore("synthetic").read()
    assert (t.via, t.question, t.thread_id, t.text) == ("cli", "Who knows Auth?",
                                                        answer.thread_id, "None.")  # fmt: skip

    [chat] = history.list_threads(2**62, 10)  # the offline turn is not kept either
    turn = history.get_thread(chat.id).turns[0]
    assert (chat.id, chat.turns, turn.status, turn.answer["text"]) == (
        answer.thread_id, 1, "done", "None.")  # fmt: skip
    assert turn.answer["trace_id"] == t.id

    out = CliRunner().invoke(cli.app, ["traces", "synthetic"])
    assert out.exit_code == 0 and "1 turns in the last 7 days (1 answered)" in out.output
    assert "zero_source" in out.output and "100%" in out.output


# --- thumbs-down drafts -----------------------------------------------------------------------


def test_thumbs_down_turns_become_draft_cases_with_their_thread(root, capsys):
    store = TraceStore("synthetic")
    store.add(trace(1, thread_id="th", question="Who owns Billing?"))
    store.add(trace(2, thread_id="th", question="And who reviews it?", cited=["person:bob"]))
    store.add(trace(3, question="Liked this one"))
    store.rate("t2", "down", "bob left; erin reviews now")
    store.rate("t3", "up")
    path = root / "cases.yaml"
    path.write_text("- id: kept\n  turns:\n    - question: Hi?\n")

    assert drafts.main(["--slug", "synthetic", "--write", "--cases", str(path)]) == 0
    text = path.read_text()
    assert "# it cited: person:bob" in text and "TODO: write expect" in text
    loaded = cases.load("synthetic", path)
    assert [c.id for c in loaded] == ["kept", "fb-t2"]
    case = loaded[1]
    assert case.tags == ["draft", "feedback"] and case.why == "bob left; erin reviews now"
    assert [t.question for t in case.turns] == ["Who owns Billing?", "And who reviews it?"]
    assert case.turns[-1].expect.answered
    assert [c.id for c in cases.select(loaded, [])] == ["kept"]  # a plain eval skips drafts
    assert [c.id for c in cases.select(loaded, ["draft"])] == ["fb-t2"]

    assert drafts.main(["--slug", "synthetic", "--write", "--cases", str(path)]) == 0
    assert path.read_text() == text  # already there: not added twice
    assert "no new thumbs-down" in capsys.readouterr().err


def test_drafts_print_as_valid_yaml_by_default(root, capsys):
    store = TraceStore("synthetic")
    store.add(trace(1, stop="no_answer", text=None, sources=0, cited=[]))
    store.rate("t1", "down")
    assert drafts.main(["--slug", "synthetic", "--cases", str(root / "none.yaml")]) == 0
    raw = yaml.safe_load(capsys.readouterr().out)
    [case] = [cases.Case.model_validate(c) for c in raw]
    assert case.id == "fb-t1" and "Thumbs down" in case.why
    assert not (root / "none.yaml").exists()


def test_a_multiline_tool_error_cannot_break_the_case_file(root):
    store = TraceStore("synthetic")
    error = "x failed: ValidationError: 1 error\nsystem\n  Field required: [type=missing]"
    store.add(trace(1, tool_errors=[error], text="Line one.\n\n- item: [1]"))
    store.rate("t1", "down", "wrong\nall: wrong")
    path = root / "cases.yaml"
    assert drafts.main(["--slug", "synthetic", "--write", "--cases", str(path)]) == 0
    [case] = cases.load("synthetic", path)
    assert case.why == "wrong\nall: wrong"  # kept whole: it is a YAML string, not a comment
    assert not list(root.glob(".*.tmp"))
