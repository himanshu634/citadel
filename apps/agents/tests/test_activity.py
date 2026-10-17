"""Agent activity: an Ask chat's turns as runs (pure)."""

from __future__ import annotations

from datetime import UTC, datetime

from agents.activity import runs_from_thread
from agents.history import ChatStep, ChatTurn, Thread

T0 = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)


def step(tool, status="done", error=None, nodes=()):
    return ChatStep(id=tool, tool=tool, status=status, error=error, nodes=list(nodes))


def test_steps_keep_order_status_and_unique_touched_uids():
    turn = ChatTurn(
        n=2,
        question="Who owns Auth?",
        status="running",
        started_at=T0,
        steps=[
            step("work_history", nodes=[{"uid": "system:Auth"}, {"uid": "pr:1"}, {"uid": "pr:1"}]),
            step("impact_of", error="boom"),
            step("experts_for_system", status="running"),
        ],
    )
    thread = Thread(id="t", title="x", created_at=T0, updated_at=T0, last_status="running",
                    turns=[turn])  # fmt: skip
    [run] = runs_from_thread(thread)
    assert (run.id, run.status, run.thread_id) == ("ask:t:2", "running", "t")
    assert [(s.n, s.tool, s.status) for s in run.steps] == [
        (1, "work_history", "done"), (2, "impact_of", "failed"),
        (3, "experts_for_system", "running")]  # fmt: skip
    assert run.steps[0].touched == ["system:Auth", "pr:1"]
