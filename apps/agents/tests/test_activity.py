"""Agent activity: an Ask chat's turns as runs (pure)."""

from __future__ import annotations

from datetime import UTC, datetime

from agents.activity import runs_from_reviews, runs_from_thread
from agents.history import ChatStep, ChatTurn, Thread
from agents.keeper.model import Review, ReviewStep

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


# --- Keeper reviews ---------------------------------------------------------------------------


def review(uid="review:1", state="done", trigger="manual", gaps=(), gap_text=None, **kw):
    return Review(uid=uid, slug="s", trigger=trigger, state=state, budget=3, gaps=list(gaps),
                  gap_text=gap_text, started_at="2026-10-17T09:00:00Z", **kw)  # fmt: skip


def rstep(n, actor="pm", tool="work_history", status="done", **kw):
    return ReviewStep(review="review:1", n=n, actor=actor, tool=tool, status=status,
                      started_at="2026-10-17T09:00:01Z", **kw)  # fmt: skip


def test_a_review_is_a_keeper_run_with_its_steps():
    r = review(gaps=["gap:a", "gap:b", "gap:c"], gap_text="Who owns Auth?",
               ended_at="2026-10-17T09:04:00Z")  # fmt: skip
    steps = [
        rstep(
            2,
            actor="keeper",
            tool="submit_keeper_decision",
            kind="submit",
            input={"outcome": "claim"},
        ),  # fmt: skip
        rstep(1, input={"system": "Auth"}, count=2, touched=["system:Auth", "pr:1"]),
    ]
    [run] = runs_from_reviews([r], {"review:1": steps}, live=lambda uid: False)
    assert (run.id, run.source, run.actor, run.status, run.thread_id) == (
        "keeper:review:1", "keeper", "keeper", "done", None)  # fmt: skip
    assert run.title == "Who owns Auth? (+2 more)"
    assert run.started_at == datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
    assert run.ended_at == datetime(2026, 10, 17, 9, 4, tzinfo=UTC)
    assert [(s.n, s.actor, s.tool, s.kind) for s in run.steps] == [
        (1, "pm", "work_history", "graph"),
        (2, "keeper", "submit_keeper_decision", "submit"),
    ]
    assert (run.steps[0].input, run.steps[0].count, run.steps[0].touched) == (
        {"system": "Auth"}, 2, ["system:Auth", "pr:1"])  # fmt: skip


def test_review_titles():
    def title(**kw):
        [run] = runs_from_reviews([review(**kw)], {"review:1": [rstep(1)]}, live=lambda u: False)
        return run.title

    assert title(gaps=["gap:a"], gap_text="Who owns Auth?") == "Who owns Auth?"
    assert title(trigger="build") == "Keeper review after a build"
    assert title(trigger="manual") == "Keeper review on request"
    assert title(trigger="approval") == "Keeper review after an approval"


def test_review_status_and_liveness():
    states = ["running", "running", "done", "stopped", "failed", "skipped"]
    reviews = [review(uid=f"review:{i}", state=st) for i, st in enumerate(states)]
    steps = {r.uid: [rstep(1, status="running")] for r in reviews}
    runs = runs_from_reviews(reviews, steps, live=lambda uid: uid == "review:0")
    assert [r.status for r in runs] == ["running", "stopped", "done", "stopped", "failed", "done"]
    # A step left running in a run nothing can finish is not shown as working now.
    assert [r.steps[0].status for r in runs] == ["running"] + ["failed"] * 5
    assert runs[1].steps[0].error == "interrupted"


def test_skipped_reviews_without_steps_are_left_out():
    reviews = [review(uid="review:1", state="skipped"), review(uid="review:2", state="done"),
               review(uid="review:3", state="skipped")]  # fmt: skip
    runs = runs_from_reviews(reviews, {"review:3": [rstep(1)]}, live=lambda uid: False)
    assert [r.id for r in runs] == ["keeper:review:2", "keeper:review:3"]
