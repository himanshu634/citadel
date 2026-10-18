"""Agent roles and the runner, offline: a scripted client, the Keeper's in-memory ledger and a
fake brain, no API key and no database."""

from __future__ import annotations

import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from agents import acl
from agents.keeper.model import gap_uid
from agents.keeper.store import MemoryKeeperStore
from agents.roles import ROLES, Ctx
from agents.runner import grounding, missing_tools, run_job
from agents.testing import fake_brain
from agents.work.submits import SUBMITS, SubmitConsult
from anthropic.types.beta import BetaToolUseBlock, BetaUsage
from brain.config import get_settings

NOW = 2_000_000


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- the registry -----------------------------------------------------------------------------


def test_every_role_is_registered_with_a_user_sorted_tools_and_prompts():
    assert list(ROLES) == ["pm", "qa", "brain", "keeper", "archivist"]
    for role in ROLES.values():
        assert role.db_user in acl.PERMISSIONS
        assert list(role.read_tools) == sorted(role.read_tools), role.name
        if role.jobs:
            assert role.prompt.startswith("You are one agent") and "# Role" in role.prompt
            for job in role.jobs:
                assert f"`{job.name}`" in role.prompt, (role.name, job.name)
    assert {j.submit.name for r in ROLES.values() for j in r.jobs} == set(SUBMITS)


def test_every_read_tool_is_a_graph_tool():
    assert {r.name: missing_tools(r) for r in ROLES.values() if missing_tools(r)} == {}


def test_submit_tools_have_json_schemas():
    for submit in SUBMITS.values():
        tool = json.loads(json.dumps(submit.tool()))
        assert tool["name"].startswith("submit_") and tool["description"]
        assert "cites" in tool["input_schema"]["properties"]
        # cites may be empty only where "nothing grounded" is an answer (Keeper consult/decide,
        # the Archivist's nothing_found)
        optional = submit.name in (
            "submit_consult",
            "submit_keeper_decision",
            "submit_archive_answer",
        )
        assert ("cites" in tool["input_schema"]["required"]) is not optional, submit.name


def test_only_the_keeper_and_the_loader_write_the_brain():
    for user in acl.PERMISSIONS:
        writes = acl.can(user, "synthetic", "brain_synthetic", "W")
        assert writes is (user in ("citadel_keeper", "citadel_loader")), user


# --- grounding --------------------------------------------------------------------------------

GROUNDED = {
    "can_ground": True,
    "kind": "fact",
    "subject_uid": "fake:pr:2",
    "statement": "The refresh token rotation race was fixed in PR 2.",
    "cites": ["fake:pr:2"],
}


def test_grounding_checks_shape_subject_and_seen_uids():
    subject = SimpleNamespace(uid="consult:1")
    check = grounding(SubmitConsult, subject)
    ok = {"consult": "consult:1", **GROUNDED}
    assert check(ok, {"fake:pr:2": {}}) is None
    assert "did not appear" in check(ok, {})
    assert "must be consult:1" in check({**ok, "consult": "consult:9"}, {"fake:pr:2": {}})
    assert "invalid submit_consult" in check({**ok, "statement": None}, {"fake:pr:2": {}})


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


def qa_consult() -> tuple[MemoryKeeperStore, str]:
    """A ledger with one gap in review and one open qa consult on it."""
    s = MemoryKeeperStore("synthetic")
    text = "Why did the auth refresh token race happen?"
    [row] = s.write(
        "ledger/open_gap",
        "citadel_brain",
        {"uid": gap_uid(), "kind": "failed_question", "text": text, "norm": text.lower(),
         "now": NOW - 60},
    )  # fmt: skip
    gap = row["uid"]
    s.write(
        "ledger/set_gap_status",
        "citadel_keeper",
        {"uid": gap, "from": ["open"], "to": "in_review", "now": NOW - 50},
    )
    s.write(
        "ledger/post_consult",
        "citadel_keeper",
        {"gap": gap, "role": "qa", "attempt": 0, "now": NOW - 40},
    )
    return s, gap


def run_qa(s: MemoryKeeperStore, client):
    role = ROLES["qa"]
    job = role.job("consult")
    ctx = Ctx("agent:qa-1", role.db_user, NOW)
    [subject] = job.queue(s, ctx)
    return subject, run_job(s, role, job, subject, ctx, client=client, graph_run=fake_brain)


def episodes(s: MemoryKeeperStore) -> list[dict]:
    return [e for e in s.read("ledger/read_log", {"limit": 50}) if e["action"] == "episode"]


def test_a_role_runs_through_the_real_loop_with_claude():
    """The LLM path: role prompt, role tools + one submit tool, grounding retry, then a write."""
    s, gap = qa_consult()
    role = ROLES["qa"]
    [subject] = role.job("consult").queue(s, Ctx("agent:qa-1", role.db_user, NOW))
    answer = {"consult": subject.uid, **GROUNDED}
    client = FakeClaude(
        [("submit_consult", answer)],  # nothing looked up yet: refused
        [("work_history", {"system": "Auth"})],
        [("submit_consult", answer)],
    )
    _, result = run_qa(s, client)

    assert result.stop is None and result.tools_called == ["work_history"]
    [c] = s.read("ledger/consults_for_gap", {"gap": gap})
    assert c["status"] == "answered" and c["can_ground"] is True and c["cites"] == ["fake:pr:2"]
    first = client.requests[0]
    assert first["system"][0]["text"] == role.prompt
    assert [t["name"] for t in first["tools"]] == [*sorted(role.read_tools), "submit_consult"]
    assert "<context>" in first["messages"][0]["content"][0]["text"]
    refused = client.requests[1]["messages"][-1]["content"][0]
    assert refused["is_error"] and "fake:pr:2" in refused["content"]
    [episode] = episodes(s)
    assert episode["why"].startswith(f"qa.consult {subject.uid}")


def test_a_run_without_a_decision_writes_nothing_and_is_logged():
    s, gap = qa_consult()
    bad = [("submit_consult", {"can_ground": True})]  # missing fields: refused each time
    client = FakeClaude(bad, bad, [], [])  # then gives up, even after the nudge
    _, result = run_qa(s, client)
    assert result.stop is not None and not result.rows
    [c] = s.read("ledger/consults_for_gap", {"gap": gap})
    assert c["status"] == "open"
    assert len(episodes(s)) == 1


def test_a_failing_api_call_is_logged():
    s, _ = qa_consult()

    class Down:
        beta = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: 1 / 0))

    _, result = run_qa(s, Down())
    assert result.stop.startswith("error: ZeroDivisionError")
    [episode] = episodes(s)
    assert "ZeroDivisionError" in episode["why"]
