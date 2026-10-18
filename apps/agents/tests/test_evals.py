"""The eval harness (agents/evals) with a scripted client: no API, no database."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest
from agents.evals import cases, report, run
from agents.evals.cases import Case, Expect, Gold, GoldResolver
from agents.evals.graders import grade
from agents.keeper import interview
from agents.testing import FakeClient, reply, submit, tool_use
from agents.traces import step_summary
from brain import tools
from pydantic import BaseModel

# --- the case file ----------------------------------------------------------------------------


def _refs(expect: Expect) -> list:
    return [*expect.cite_any, *expect.cite_all, *expect.cite_none]


@pytest.mark.parametrize("slug", [p.stem for p in cases.CASES_DIR.glob("*.yaml")])
def test_case_files_name_real_tools_and_row_fields(slug):
    """A typo in a case file should fail here, not after paying for a run."""
    loaded = cases.load(slug)
    assert loaded
    for case in loaded:
        for turn in case.turns:
            e = turn.expect
            for name in [*e.tools_any, *e.tools_all, *e.tools_none]:
                assert name in tools.TOOLS or name in interview.TOOLS, f"{case.id}: unknown {name}"
            for ref in _refs(e):
                if isinstance(ref, Gold):
                    tool = tools.TOOLS.get(ref.tool)
                    assert tool, f"{case.id}: unknown gold tool {ref.tool}"
                    tool.params.model_validate(ref.params)
                    fields = {f.alias or n for n, f in tool.row.model_fields.items()}
                    assert ref.field in fields, f"{case.id}: {ref.tool} rows have no {ref.field}"


def test_select_by_id_or_tag():
    a = Case(id="a", tags=["x"], turns=[{"question": "?"}])
    b = Case(id="b", tags=["y"], turns=[{"question": "?"}])
    assert cases.select([a, b], []) == [a, b]
    assert cases.select([a, b], ["b"]) == [b]
    assert cases.select([a, b], ["x"]) == [a]


def test_duplicate_ids_are_refused(tmp_path):
    f = tmp_path / "x.yaml"
    f.write_text("- {id: a, turns: [{question: q}]}\n- {id: a, turns: [{question: q}]}\n")
    with pytest.raises(ValueError, match="duplicate"):
        cases.load("x", f)


# --- gold -------------------------------------------------------------------------------------


class ExpertRow(BaseModel):
    login: str
    person_uid: str


def test_gold_reads_the_top_rows_once():
    calls = []

    def fake_run(slug, name, **params):
        calls.append((slug, name, params))
        return [ExpertRow(login="alice", person_uid="person:alice"),
                ExpertRow(login="carol", person_uid="person:carol")]  # fmt: skip

    g = GoldResolver("synthetic", fake_run)
    ref = Gold(tool="experts_for_system", params={"system": "Auth"}, field="person_uid", top=2)
    assert g.uids(["person:x", ref]) == ["person:x", "person:alice", "person:carol"]
    assert g.uids([ref]) == ["person:alice", "person:carol"]
    assert len(calls) == 1


def test_empty_gold_stops_the_run():
    g = GoldResolver("synthetic", lambda *a, **k: [])
    with pytest.raises(ValueError, match="is the graph loaded"):
        g.uids([Gold(tool="experts_for_system", field="person_uid")])


# --- graders ----------------------------------------------------------------------------------


def _gold(**kw):
    return {"cite_any": [], "cite_all": [], "cite_none": [], **kw}


def _failed(checks):
    return sorted(c.name for c in checks if not c.ok)


def test_a_good_answer_passes_every_check():
    e = Expect(tools_any=["experts_for_system"], text_all=["Alice"], text_none=["bot"],
               text_re=r"\bexpert\b", max_steps=2)  # fmt: skip
    checks = grade(
        e,
        _gold(cite_any=["person:alice"], cite_none=["person:ci-bot"]),
        text="alice is the Auth expert [1].",
        cited=["person:alice"],
        tools=["experts_for_system"],
    )
    assert _failed(checks) == []
    assert {c.name for c in checks} == {
        "answered", "cite_any", "cite_none", "tools_any", "text_all", "text_none", "text_re",
        "max_steps",
    }  # fmt: skip


def test_each_check_fails_on_its_own():
    e = Expect(tools_all=["impact_of"], tools_none=["graph_stats"], text_any=["web"],
               text_all=["billing"], text_none=["ci-bot"], max_steps=1)  # fmt: skip
    checks = grade(
        e,
        _gold(cite_any=["system:Web app"], cite_all=["pr:1"], cite_none=["person:ci-bot"]),
        text="ci-bot did it",
        cited=["person:ci-bot"],
        tools=["graph_stats", "graph_stats"],
    )
    assert _failed(checks) == [
        "cite_all", "cite_any", "cite_none", "max_steps", "text_all", "text_any", "text_none",
        "tools_all", "tools_none",
    ]  # fmt: skip


def test_a_tool_that_failed_did_not_run():
    """tools_any/all count only calls that returned rows; tools_none and max_steps count every
    call (an attempt is still the wrong move, and still a step)."""
    e = Expect(tools_any=["semantic_search"], tools_none=["record_testimony"], max_steps=2)
    checks = grade(
        e,
        _gold(),
        text="ok",
        cited=[],
        tools=["semantic_search", "record_testimony"],
        failed=["semantic_search", "record_testimony"],
    )
    assert _failed(checks) == ["tools_any", "tools_none"]


def test_no_answer_fails_once_and_stops_grading():
    checks = grade(Expect(text_all=["x"]), _gold(), text=None, cited=[], tools=[])
    assert [(c.name, c.ok) for c in checks] == [("answered", False)]


def test_step_summary_splits_tools_errors_and_rejections():
    steps = [
        {"tool": "experts_for_system", "ms": 5, "error": None},
        {"tool": "list_systems", "ms": 3, "error": "boom"},
        {"tool": "submit_answer", "error": "These uids did not appear"},
        {"tool": "submit_answer", "error": None},
    ]
    s = step_summary(steps, "submit_answer")
    assert s == {
        "tools": ["experts_for_system", "list_systems"],
        "tool_errors": ["list_systems: boom"],
        "rejected": ["These uids did not appear"],
        "tool_ms": 8,
    }


# --- a whole run with a scripted client -------------------------------------------------------


@dataclass
class FakeTool:
    name: str
    description: str
    params: type[BaseModel]


class ExpertParams(BaseModel):
    system: str


def fake_run(slug, name, **params):
    return [ExpertRow(login="alice", person_uid="person:alice")]


TOOLSET = run.Toolset(
    tools={"experts_for_system": FakeTool("experts_for_system", "Experts.", ExpertParams)},
    run=fake_run,
)

CASE = Case.model_validate(
    {
        "id": "auth",
        "turns": [
            {
                "question": "Who knows Auth?",
                "expect": {
                    "cite_any": [{"tool": "experts_for_system", "params": {"system": "Auth"},
                                  "field": "person_uid"}],
                    "tools_any": ["experts_for_system"],
                    "text_all": ["alice"],
                },
            },
            {"question": "And her team?", "expect": {"text_all": ["identity"]}},
        ],
    }
)  # fmt: skip


def test_run_case_grades_every_turn_in_one_thread():
    client = FakeClient(
        reply(tool_use("t1", "experts_for_system", {"system": "Auth"})),
        reply(submit("t2", "bob [1].", ["person:nobody"])),  # rejected: uid never seen
        reply(submit("t3", "alice [1].", ["person:alice"])),
        reply(submit("t4", "She is on identity [1].", ["person:alice"])),
    )
    gold = GoldResolver("synthetic", fake_run)
    r = run.run_case(CASE, "synthetic", gold, client=client, toolset=TOOLSET)

    assert r["passed"] is True and r["error"] is None
    first, second = r["turns"]
    assert first["tools"] == ["experts_for_system"]
    assert len(first["rejected"]) == 1 and "person:nobody" in first["rejected"][0]
    assert first["sources"] == ["person:alice"]
    assert first["usage"]["input_tokens"] == 300  # three calls, 100 each
    assert second["tools"] == [] and second["passed"]
    # The follow-up went out in the same thread: the first turn is in its history.
    last = client.requests[-1]["messages"]
    assert last[0]["content"][0]["text"].endswith("Who knows Auth?")
    assert last[-1]["content"][0]["text"].endswith("And her team?")


def test_a_failing_turn_fails_the_run_and_an_exception_is_recorded():
    client = FakeClient(reply(submit("t1", "carol.", [])))
    gold = GoldResolver("synthetic", fake_run)
    r = run.run_case(CASE, "synthetic", gold, client=client, toolset=TOOLSET)
    assert r["passed"] is False
    assert r["error"] and "IndexError" in r["error"]  # the script has no reply for turn 2
    assert len(r["turns"]) == 1
    failed = {c["name"] for c in r["turns"][0]["checks"] if not c["ok"]}
    assert failed == {"cite_any", "tools_any", "text_all"}


def test_report_and_baseline(tmp_path, monkeypatch):
    def result(case, passed, rep=0):
        usage = {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 80,
                 "cache_creation_input_tokens": 10}  # fmt: skip
        turn = {"tools": ["x"], "rejected": [], "tool_errors": [], "ms": 1000, "passed": passed,
                "usage": usage, "checks": [], "stop": "tool_use", "text": "t"}  # fmt: skip
        return {"kind": "run", "case": case, "repeat": rep, "passed": passed, "error": None,
                "turns": [turn]}  # fmt: skip

    before = [result("a", True), result("a", True), result("b", True)]
    now = [result("a", True), result("a", False, 1), result("c", True)]
    monkeypatch.setattr(run, "OUT_DIR", tmp_path)
    path = run.write(before, {"model": "m", "effort": "low"}, "synthetic")
    assert json.loads(path.read_text().splitlines()[0])["kind"] == "meta"
    assert len(run.load_results(path)) == 3

    text = run.report(now, run.summarize(run.load_results(path)))
    assert "-50%  REGRESSED" in text
    assert "new" in text.splitlines()[2]  # case c
    assert "2/3 runs passed" in text
    assert "total in 300 (cached 240), out 15" in text  # cache reads and writes count as input
    assert "FAIL a #1" in text


def test_markdown_report_compares_two_files_per_company(tmp_path):
    def result(case, tags, passed, rep, error=None):
        check = {"name": "cite_any", "ok": passed, "detail": "none of ['person:alice']"}
        usage = {"input_tokens": 100, "output_tokens": 10, "cache_read_input_tokens": 0}
        turn = {"tools": ["x", "y"], "rejected": [], "tool_errors": [], "ms": 2000,
                "usage": usage, "checks": [check], "passed": passed,
                "sources": ["system:Auth"]}  # fmt: skip
        return {"kind": "run", "case": case, "tags": tags, "repeat": rep, "passed": passed,
                "error": error, "turns": [] if error else [turn]}  # fmt: skip

    def write(name, model, runs):
        meta = {"kind": "meta", "slug": "acme", "model": model, "effort": "medium", "repeat": 2,
                "cases": ["who", "why"], "started": "2026-10-17T00:00:00+00:00"}  # fmt: skip
        path = tmp_path / name
        path.write_text("\n".join(json.dumps(x) for x in [meta, *runs]) + "\n")
        return path

    base = write("a.jsonl", "claude-haiku-5-5", [
        result("who", ["experts"], True, 0), result("who", ["experts"], False, 1),
        result("why", ["live", "history"], True, 0), result("why", ["live", "history"], True, 1),
    ])  # fmt: skip
    other = write("b.jsonl", "claude-sonnet-5-5", [
        result("who", ["experts"], True, 0), result("who", ["experts"], True, 1),
        result("why", ["live", "history"], True, 0),
        result("why", ["live", "history"], False, 1, error="APIStatusError: overloaded"),
    ])  # fmt: skip

    text = report.render([base, other])
    lines = text.splitlines()
    assert lines[0] == "| Company | Cases | haiku-5-5 medium | sonnet-5-5 medium | Δ |"
    assert lines[2] == "| acme | 2 | 3/4 (75%) | 3/4 (75%) | = |"
    assert "commit not recorded" in text  # older files have no commit in their meta
    assert "| experts | 1 | 1/2 (50%) | 2/2 (100%) | +50 pt |" in text
    assert "| history | 1 | 2/2 (100%) | 1/2 (50%) | -50 pt |" in text  # `live` is not a group
    assert "| runs that errored (API or graph) | 0 | 1 |" in text
    assert "| cases passed every run | 1/2 | 1/2 |" in text
    assert "| graph tool calls | 2.0 | 1.5 |" in text  # an errored run made no calls
    assert "| `why` | history | 2/2 | 1/2 (1 err) | -50 pt |" in text
    assert (
        "- `who` #1 (haiku-5-5 medium): turn 1 cite_any: none of ['person:alice'] "
        "(cited system:Auth)"
    ) in text
    assert "- `why` #1 (sonnet-5-5 medium): error: APIStatusError: overloaded" in text

    # The same model before and after a change: the two columns get told apart.
    again = write("c.jsonl", "claude-haiku-5-5", [result("who", ["experts"], True, 0)])
    lines = report.render([base, again]).splitlines()
    head = "| Company | Cases | haiku-5-5 medium (before) | haiku-5-5 medium (after) | Δ |"
    assert lines[0] == head
    assert lines[2] == "| acme | 2 | 3/4 (75%) | 1/1 (100%) | +25 pt |"
