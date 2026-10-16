"""Agent roles, the runner and the scenarios, offline: policies and a fake brain, no API key and
no database. One test runs the sprint against the real synthetic graph (needs `make up`)."""

from __future__ import annotations

import json
from collections import Counter
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from agents import acl
from agents.roles import ROLES, Ctx
from agents.runner import grounding, missing_tools, run_job
from agents.sim import scenarios
from agents.testing import fake_brain
from agents.work.memory_store import MemoryStore
from agents.work.submits import SUBMITS, SubmitQa
from anthropic.types.beta import BetaToolUseBlock, BetaUsage
from brain.config import get_settings
from brain.testing import needs_graph


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- the registry -----------------------------------------------------------------------------


def test_every_role_is_registered_with_a_user_sorted_tools_and_prompts():
    assert list(ROLES) == [
        "pm",
        "developer",
        "qa",
        "devops",
        "builder",
        "critic",
        "risk",
        "brain",
        "reviewer",
    ]
    for role in ROLES.values():
        assert role.db_user in acl.PERMISSIONS and acl.ROLE_OF[role.db_user] == role.name
        assert list(role.read_tools) == sorted(role.read_tools), role.name
        if role.jobs:
            assert role.prompt.startswith("You are one agent") and "# Role" in role.prompt
            for job in role.jobs:
                assert f"`{job.name}`" in role.prompt, (role.name, job.name)
    assert {j.submit.name for r in ROLES.values() for j in r.jobs} == set(SUBMITS)


def test_tools_still_missing_are_pinned():
    """Role read tools that need phase 2 queries (vector search, derive scores). This list only
    shrinks: each tool gets its queries/tools/*.cypher and leaves it."""
    missing = {r.name: missing_tools(r) for r in ROLES.values() if missing_tools(r)}
    assert missing == {
        "pm": ["semantic_similar_tasks"],
        "developer": ["files_for_system"],
        "qa": ["past_regressions"],
        "risk": ["best_first_contact", "bottleneck_people", "single_expert_systems"],
        "reviewer": ["community_of"],
    }


def test_submit_tools_have_json_schemas():
    for submit in SUBMITS.values():
        tool = json.loads(json.dumps(submit.tool()))
        assert tool["name"].startswith("submit_") and tool["description"]
        assert "cites" in tool["input_schema"]["required"]


def test_risk_writes_only_its_own_memory():
    """Ground rule 5: the watchdog's database user is read-only on the brain."""
    s = MemoryStore("synthetic")
    assert not acl.can("citadel_risk", "synthetic", "brain_synthetic", "W")
    with pytest.raises(acl.Refused):
        s.write("work/write_episode", "citadel_risk", {"agent": "agent:risk-1", "now": 1})


# --- grounding --------------------------------------------------------------------------------


def test_grounding_checks_shape_subject_and_seen_uids():
    subject = SimpleNamespace(uid="task:1")
    check = grounding(SubmitQa, subject)
    ok = {
        "task": "task:1",
        "verdict": "failed",
        "test_plan": ["x"],
        "reason": "r",
        "regression": "pr:2",
        "cites": ["pr:2"],
    }
    assert check(ok, {"pr:2": {}}) is None
    assert "did not appear" in check(ok, {})
    assert "must be task:1" in check({**ok, "task": "task:9"}, {"pr:2": {}})
    assert "invalid submit_qa" in check({**ok, "cites": []}, {"pr:2": {}})


class FakeClaude:
    """Scripted Messages API replies, recording requests (as in test_agent.py)."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kw):
        self.requests.append(json.loads(json.dumps(kw)))
        blocks = [
            BetaToolUseBlock(type="tool_use", id=f"c{len(self.requests)}_{i}", name=n, input=inp)
            for i, (n, inp) in enumerate(self.turns.pop(0))
        ]
        stop = "tool_use" if blocks else "end_turn"
        msg = SimpleNamespace(
            content=blocks,
            stop_reason=stop,
            stop_details=None,
            model="claude-haiku-5-5",
            usage=BetaUsage(input_tokens=1, output_tokens=1),
        )
        return nullcontext(SimpleNamespace(get_final_message=lambda: msg))


def qa_ready_store() -> MemoryStore:
    s = MemoryStore("synthetic")
    scenarios.seed_triaged(s, [{"title": "Shorten token lifetime", "system": "system:Auth"}])
    s.tasks["task:1"] = s.tasks["task:1"].model_copy(
        update={
            "status": "done",
            "qa": "pending",
            "pm": "pending",
            "assignee": "agent:dev-1",
            "plan": "Change services/auth/**",
            "report": "Done",
        }
    )
    return s


def test_a_role_runs_through_the_real_loop_with_claude():
    """The LLM path: role prompt, role tools + one submit tool, grounding retry, then a write."""
    s = qa_ready_store()
    role = ROLES["qa"]
    fail = {
        "task": "task:1",
        "verdict": "failed",
        "test_plan": ["re-test race"],
        "reason": "Misses the rotation race",
        "regression": "fake:pr:2",
    }
    client = FakeClaude(
        [("submit_qa", {**fail, "cites": ["fake:pr:2"]})],  # nothing looked up yet: refused
        [("work_history", {"system": "Auth"})],
        [("submit_qa", {**fail, "cites": ["fake:pr:2"]})],
    )
    ctx = Ctx("agent:qa-1", role.db_user, 2_000_000)
    [subject] = role.jobs[0].queue(s, ctx)
    result = run_job(s, role, role.jobs[0], subject, ctx, client=client, graph_run=fake_brain)

    assert result.stop is None and result.tools_called == ["work_history"]
    t = s.tasks["task:1"]
    assert (t.status, t.qa, t.last_reason) == ("in_progress", "failed", "Misses the rotation race")
    first = client.requests[0]
    assert first["system"][0]["text"] == role.prompt
    assert [t["name"] for t in first["tools"]] == [
        *sorted(n for n in role.read_tools if n not in missing_tools(role)),
        "submit_qa",
    ]
    assert "<context>" in first["messages"][0]["content"][0]["text"]
    refused = client.requests[1]["messages"][-1]["content"][0]
    assert refused["is_error"] and "fake:pr:2" in refused["content"]
    kinds = [a.kind for a in s.actions]
    assert kinds[-2:] == ["qa_started", "qa_failed"]
    assert s.actions[-1].cites == ["fake:pr:2"]
    [episode] = s.episodes
    assert episode.input == "qa.test task:1" and episode.actions == [s.actions[-1].uid]


def test_a_run_without_a_decision_gives_the_claim_back():
    s = qa_ready_store()
    role = ROLES["qa"]
    bad = [("submit_qa", {"task": "task:1"})]  # missing fields: refused each time
    client = FakeClaude(bad, bad, [], [])  # then gives up, even after the nudge
    ctx = Ctx("agent:qa-1", role.db_user, 2_000_000)
    [subject] = role.jobs[0].queue(s, ctx)
    result = run_job(s, role, role.jobs[0], subject, ctx, client=client, graph_run=fake_brain)
    assert result.stop is not None and s.tasks["task:1"].qa == "pending"
    assert s.episodes[0].stop == result.stop


def test_a_failing_api_call_gives_the_claim_back_and_is_logged():
    s = qa_ready_store()
    role = ROLES["qa"]

    class Down:
        beta = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: 1 / 0))

    ctx = Ctx("agent:qa-1", role.db_user, 2_000_000)
    [subject] = role.jobs[0].queue(s, ctx)
    result = run_job(s, role, role.jobs[0], subject, ctx, client=Down(), graph_run=fake_brain)
    assert result.stop.startswith("error: ZeroDivisionError")
    assert s.tasks["task:1"].qa == "pending" and s.episodes[0].stop == result.stop


# --- scenarios (offline policies + fake brain) ------------------------------------------------


def from_issues(s: MemoryStore):
    return [t for t in s.tasks.values() if t.from_issue]


def test_sprint_takes_ten_issues_from_open_to_released():
    sim = scenarios.sprint("synthetic", graph_run=fake_brain)
    sim.run(80)
    s = sim.store
    tasks = from_issues(s)
    assert len(tasks) == 10
    rejected = [t for t in tasks if t.status == "rejected"]
    assert len(rejected) == 2 and all(t.duplicate_of for t in rejected)
    assert {t.duplicate_of for t in rejected} == {"task:1", "task:4"}
    released = [t for t in tasks if t.status != "rejected"]
    assert len(released) == 8 and all(t.status == "released" for t in released)
    assert all(t.system and 2 <= len(t.acceptance) <= 4 for t in released)
    # Builder: every released task has a decision or an explicit "none".
    for t in released:
        made = [d for d in s.decisions.values() if d.made_in == t.uid]
        none = [a for a in s.actions if a.kind == "no_decision" and a.task == t.uid]
        assert made or none, t.uid
    # Every run left an Episode (the read-only watchdog's in its own memory graph).
    risk = [e for e in s.memory["mem_synthetic_risk"] if hasattr(e, "input")]
    assert len(s.episodes) + len(risk) == sum(len(t.runs) for t in sim.ticks)
    assert all(a.agent for a in s.actions)
    assert sim.idle(sim.ticks[-1])


def test_the_race_gives_three_tasks_to_three_developers_every_time():
    for _ in range(20):
        sim = scenarios.race("synthetic", graph_run=fake_brain)
        sim.tick()
        claimed = [a for a in sim.store.actions if a.kind == "claimed"]
        assert len(claimed) == 3
        assert len({a.agent for a in claimed}) == 3
        assert len({a.task for a in claimed}) == 3


def test_regression_loop_fails_reworks_passes_and_learns():
    sim = scenarios.regression("synthetic", graph_run=fake_brain)
    sim.run(40)
    s = sim.store
    kinds = {uid: [a.kind for a in s.actions if a.task == uid] for uid in s.tasks}
    t1 = kinds["task:1"]
    assert t1.index("qa_failed") < t1.index("qa_passed")  # failed, reworked, then passed
    assert t1.count("completed") == 2
    failed = [a for a in s.actions if a.kind == "qa_failed"]
    assert {a.task for a in failed} == {"task:1", "task:2"}
    assert all("fake:pr:2" in a.cites for a in failed)
    [lesson] = s.read("memory/lessons", {"system": "system:Auth"})
    assert lesson["regression"] == "fake:pr:2"
    # With the lesson learned, the third task covers the regression and passes first time.
    assert "qa_failed" not in kinds["task:3"] and "qa_passed" in kinds["task:3"]
    assert "fake:pr:2" in s.tasks["task:3"].plan


def test_devops_ships_two_trains_with_impacts_and_owners():
    s = MemoryStore("synthetic", co_changes=[("system:Billing", "system:Web app", 3)])
    uids = scenarios.seed_triaged(
        s,
        [
            {"title": f"t{i}", "system": sys}
            for i, sys in enumerate(["system:Auth"] * 3 + ["system:Billing"] * 3)
        ],
    )
    for uid in uids:
        s.tasks[uid] = s.tasks[uid].model_copy(
            update={"status": "done", "qa": "passed", "pm": "accepted"}
        )
    sim = scenarios.Orchestrator(
        s,
        scenarios.agents(["devops"]),
        scenarios.offline,
        graph_run=fake_brain,
        steps=(("devops", "release"),),
    )
    sim.run(5)
    releases = sorted(s.releases.values(), key=lambda r: r.name)
    assert [len(r.tasks) for r in releases] == [3, 3]
    auth, billing = releases
    assert [i.system for i in auth.impacts] == ["system:Auth"]
    assert [(i.system, i.depth) for i in billing.impacts] == [
        ("system:Billing", 0),
        ("system:Web app", 1),
    ]
    assert "person:alice" in auth.notify and "person:bob" in billing.notify
    assert all(t.status == "released" for t in s.tasks.values()) and not s.candidates


def test_critic_contradiction_opens_a_pm_task():
    s = MemoryStore("synthetic")
    scenarios.seed_triaged(s, [{"title": "a", "system": "system:Auth"}] * 2)
    for uid in s.tasks:
        s.tasks[uid] = s.tasks[uid].model_copy(update={"status": "released"})
    for ts, uid, summary in [
        (100, "task:1", "Auth keeps sessions in Redis"),
        (200, "task:2", "Auth no longer keeps sessions in Redis"),
    ]:
        s.write(
            "work/record_decisions",
            "citadel_builder",
            {
                "agent": "agent:builder-1",
                "now": ts,
                "task": uid,
                "cites": ["x"],
                "decisions": [{"summary": summary, "rationale": "r", "systems": ["system:Auth"]}],
            },
        )
    sim = scenarios.Orchestrator(
        s,
        scenarios.agents(["critic"]),
        scenarios.offline,
        graph_run=fake_brain,
        steps=(("critic", "check"),),
    )
    sim.run(5)
    assert s.decisions["decision:2"].contradicts == ["decision:1"]
    opened = [t for t in s.tasks.values() if t.title.startswith("Resolve:")]
    assert len(opened) == 1 and opened[0].status == "open"


def test_risk_scan_records_findings_the_pm_turns_into_tasks():
    s = MemoryStore("synthetic")
    sim = scenarios.Orchestrator(
        s, scenarios.agents(["pm", "risk"]), scenarios.offline, graph_run=fake_brain
    )
    sim.tick()  # risk scans on tick 0
    findings = s.read("memory/findings", db_user="citadel_risk")
    kinds = Counter(f["kind"] for f in findings)
    assert kinds == {"owner_gap": 1, "single_expert_system": 1}  # Web app gap; Infra = dave
    assert all(a.agent != "agent:risk-1" for a in s.actions)  # nothing written to the brain
    assert s.episodes == []  # its episode went to its own memory graph
    assert [e.input for e in s.memory["mem_synthetic_risk"] if hasattr(e, "input")] == [
        "risk.scan scan:0"
    ]
    sim.tick()  # PM intake seeds them, then triages one per tick
    sim.tick()
    seeded = [t for t in s.tasks.values() if t.from_finding]
    assert len(seeded) == 2
    statuses = {t.title.split(")")[0]: t.status for t in seeded}
    assert statuses == {"Risk (owner_gap": "triaged", "Risk (single_expert_system": "rejected"}


@needs_graph
def test_sprint_on_the_real_synthetic_graph(synthetic_graph):
    """The same sprint, reading the brain through the real graph tools on brain_test_synthetic."""
    sim = scenarios.sprint(synthetic_graph)
    sim.run(80)
    tasks = from_issues(sim.store)
    assert Counter(t.status for t in tasks) == {"released": 8, "rejected": 2}
    assert any(a.kind == "qa_failed" for a in sim.store.actions)  # real past fixes found
