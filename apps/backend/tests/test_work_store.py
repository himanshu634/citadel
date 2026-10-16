"""The work layer: the move table, the in-memory store's guards and the ACL table."""

from __future__ import annotations

import threading

import pytest
from brain import acl
from brain.work import store as work_store
from brain.work.memory_store import MemoryStore
from brain.work.model import Task
from brain.work.moves import LEASE_S, MOVES

NOW = 1_000_000


def task(**kw) -> Task:
    return Task(uid="task:1", title="t", created_ts=0, updated_ts=0, **kw)


def store_with(n: int = 1, **fields) -> MemoryStore:
    s = MemoryStore("synthetic")
    for i in range(n):
        s.write(
            "work/seed_task",
            "citadel_pm",
            {"agent": "agent:pm-1", "now": NOW, "title": f"task {i}", "from_issue": f"i:{i}"},
        )
        if fields:
            s.tasks[f"task:{i + 1}"] = s.tasks[f"task:{i + 1}"].model_copy(update=fields)
    return s


def move(s: MemoryStore, name: str, user: str, agent: str, now: int = NOW, uid="task:1", **p):
    return s.write(f"work/{name}", user, {"task": uid, "agent": agent, "now": now, **p})


# --- the move table ---------------------------------------------------------------------------


def test_move_table_is_pinned():
    assert set(MOVES) == {
        "triage_task",
        "reject_task",
        "claim_task",
        "plan_task",
        "unclaim_task",
        "complete_task",
        "claim_qa",
        "qa_pass",
        "qa_fail",
        "release_qa",
        "claim_pm",
        "pm_accept",
        "pm_changes",
        "release_pm",
        "release_task",
        "expire_lease",
    }


@pytest.mark.parametrize(
    ("name", "role", "fields", "ok"),
    [
        ("claim_task", "developer", {"status": "triaged"}, True),
        ("claim_task", "qa", {"status": "triaged"}, False),  # not QA's move
        ("claim_task", "developer", {"status": "open"}, False),
        (
            "claim_task",
            "developer",
            {"status": "triaged", "assignee": "agent:dev-2", "lease_until": NOW + 1},
            False,
        ),  # held
        (
            "claim_task",
            "developer",
            {"status": "triaged", "assignee": "agent:dev-2", "lease_until": NOW - 1},
            True,
        ),  # lease ran out
        (
            "complete_task",
            "developer",
            {"status": "in_progress", "assignee": "agent:dev-1"},
            False,
        ),  # no plan yet
        (
            "complete_task",
            "developer",
            {"status": "in_progress", "assignee": "agent:dev-1", "plan": "p"},
            True,
        ),
        (
            "complete_task",
            "developer",
            {"status": "in_progress", "assignee": "agent:dev-2", "plan": "p"},
            False,
        ),  # someone else's task
        ("qa_pass", "qa", {"status": "done", "qa": "pending"}, False),  # not claimed
        ("qa_pass", "developer", {"status": "done", "qa": "testing"}, False),  # own QA
        ("release_task", "devops", {"status": "done", "qa": "passed", "pm": "pending"}, False),
        ("release_task", "devops", {"status": "done", "qa": "passed", "pm": "accepted"}, True),
        ("release_task", "qa", {"status": "done", "qa": "passed", "pm": "accepted"}, False),
    ],
)
def test_move_guards(name, role, fields, ok):
    problem = MOVES[name].problem(task(**fields), role=role, agent="agent:dev-1", now=NOW)
    assert (problem is None) is ok, problem


def test_qa_failure_goes_back_to_the_same_developer_with_a_fresh_lease():
    s = store_with(status="done", qa="testing", pm="pending", assignee="agent:dev-1", plan="p")
    assert move(s, "qa_fail", "citadel_qa", "agent:qa-1", last_reason="misses #2")
    t = s.tasks["task:1"]
    assert (t.status, t.qa, t.assignee, t.last_reason) == (
        "in_progress",
        "failed",
        "agent:dev-1",
        "misses #2",
    )
    assert t.lease_until == NOW + LEASE_S
    assert s.read("work/queue_dev_own", {"agent": "agent:dev-1", "now": NOW})[0]["uid"] == "task:1"


def test_pm_changes_requested_sends_it_back_and_completion_resets_both_gates():
    s = store_with(status="done", qa="passed", pm="reviewing", assignee="agent:dev-1", plan="p")
    assert move(s, "pm_changes", "citadel_pm", "agent:pm-1", last_reason="criterion 2")
    assert s.tasks["task:1"].status == "in_progress"
    assert move(s, "complete_task", "citadel_dev", "agent:dev-1", report="fixed")
    t = s.tasks["task:1"]
    assert (t.status, t.qa, t.pm) == ("done", "pending", "pending")


def test_a_write_that_does_not_match_changes_nothing():
    s = store_with(status="triaged")
    assert move(s, "claim_task", "citadel_dev", "agent:dev-1")
    before = s.tasks["task:1"]
    assert move(s, "claim_task", "citadel_dev", "agent:dev-2") == []  # got there first
    assert move(s, "qa_pass", "citadel_dev", "agent:dev-1") == []  # not the developer's move
    assert s.tasks["task:1"] == before
    assert [a.kind for a in s.actions] == ["seeded", "claimed"]


def test_expired_leases_go_back_to_the_queue():
    s = store_with(status="triaged")
    move(s, "claim_task", "citadel_dev", "agent:dev-1")
    assert (
        s.write(
            "work/expire_leases",
            "citadel_orchestrator",
            {"agent": "agent:orchestrator", "now": NOW + 10},
        )
        == []
    )
    rows = s.write(
        "work/expire_leases",
        "citadel_orchestrator",
        {"agent": "agent:orchestrator", "now": NOW + LEASE_S + 1},
    )
    assert rows and s.tasks["task:1"].status == "triaged" and s.tasks["task:1"].assignee is None
    assert s.actions[-1].kind == "lease_expired"


def test_claims_are_atomic_under_threads():
    s = store_with(3, status="triaged")
    barrier = threading.Barrier(15)
    won: list[str] = []

    def claim(i: int) -> None:
        agent = f"agent:dev-{i}"
        barrier.wait()
        for uid in ("task:1", "task:2", "task:3"):
            if move(s, "claim_task", "citadel_dev", agent, uid=uid):
                won.append(agent)
                return

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(15)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(won) == 3 == len(set(won))
    assert len([a for a in s.actions if a.kind == "claimed"]) == 3


# --- other writes -----------------------------------------------------------------------------


def test_seeding_is_one_task_per_issue():
    s = store_with()
    again = s.write(
        "work/seed_task",
        "citadel_pm",
        {"agent": "agent:pm-1", "now": NOW, "title": "x", "from_issue": "i:0"},
    )
    assert again == [] and len(s.tasks) == 1
    assert s.read("work/untasked_issues") == []


def test_a_release_is_all_or_nothing():
    s = store_with(2, status="done", qa="passed", pm="accepted", system="system:Auth")
    s.write("work/mark_release_candidates", "citadel_devops", {"agent": "a", "now": NOW})
    [train] = s.read("tools/release_trains")
    assert train["task_uids"] == ["task:1", "task:2"] and train["system_uids"] == ["system:Auth"]
    s.tasks["task:2"] = s.tasks["task:2"].model_copy(update={"pm": "changes_requested"})
    params = {
        "train": train["uid"],
        "agent": "agent:devops-1",
        "now": NOW,
        "release_name": "r",
        "notes": "n",
    }
    assert s.write("work/create_release", "citadel_devops", params) == []
    assert s.tasks["task:1"].status == "done" and not s.releases


def test_critic_supersede_and_contradiction_and_time_travel():
    s = store_with(status="released", system="system:Auth")
    dec = {"agent": "agent:builder-1", "task": "task:1", "cites": ["x"]}
    s.write(
        "work/record_decisions",
        "citadel_builder",
        {
            **dec,
            "now": 100,
            "decisions": [
                {
                    "summary": "Auth uses JWT sessions",
                    "rationale": "load",
                    "systems": ["system:Auth"],
                }
            ],
        },
    )
    s.tasks["task:2"] = s.tasks["task:1"].model_copy(update={"uid": "task:2"})
    s.write(
        "work/record_decisions",
        "citadel_builder",
        {
            **dec,
            "task": "task:2",
            "now": 200,
            "decisions": [
                {
                    "summary": "Auth stores JWT sessions server side",
                    "rationale": "r",
                    "systems": ["system:Auth"],
                }
            ],
        },
    )
    rel = {
        "agent": "agent:critic-1",
        "decision": "decision:2",
        "now": 200,
        "cites": ["x"],
        "relations": [{"other": "decision:1", "relation": "supersedes", "note": ""}],
    }
    assert s.write("work/relate_decision", "citadel_critic", rel)
    assert s.write("work/relate_decision", "citadel_critic", rel) == []  # checked once

    def as_of(ts):
        return [
            d["uid"] for d in s.read("tools/decisions_as_of", {"system": "system:Auth", "ts": ts})
        ]

    assert as_of(150) == ["decision:1"] and as_of(250) == ["decision:2"]
    assert s.decisions["decision:1"].status == "superseded"

    s.tasks["task:3"] = s.tasks["task:1"].model_copy(update={"uid": "task:3"})
    s.write(
        "work/record_decisions",
        "citadel_builder",
        {
            **dec,
            "task": "task:3",
            "now": 300,
            "decisions": [
                {"summary": "Auth no longer uses JWT", "rationale": "r", "systems": ["system:Auth"]}
            ],
        },
    )
    rows = s.write(
        "work/relate_decision",
        "citadel_critic",
        {
            **rel,
            "decision": "decision:3",
            "now": 300,
            "relations": [{"other": "decision:2", "relation": "contradicts"}],
        },
    )
    [opened] = rows[0]["opened"]
    assert s.tasks[opened].status == "open" and s.tasks[opened].title.startswith("Resolve:")
    assert s.read("work/queue_pm_triage", {"now": 300})[0]["uid"] == opened


def test_blast_radius_follows_co_changes_up_to_depth():
    s = MemoryStore(
        "synthetic", co_changes=[("system:A", "system:B", 3), ("system:B", "system:C", 1)]
    )
    rows = s.read("tools/blast_radius", {"system": "system:A", "depth": 1})
    assert rows == [{"system_uid": "system:B", "chain_uids": ["system:A", "system:B"], "depth": 1}]
    rows = s.read("tools/blast_radius", {"system": "system:A", "depth": 2})
    assert [(r["system_uid"], r["depth"]) for r in rows] == [("system:B", 1), ("system:C", 2)]


# --- permissions ------------------------------------------------------------------------------


def test_the_risk_watchdog_cannot_write_the_brain():
    s = store_with(status="triaged")
    with pytest.raises(acl.Refused):
        move(s, "claim_task", "citadel_risk", "agent:risk-1")
    with pytest.raises(acl.Refused):
        s.write("work/seed_task", "citadel_risk", {"agent": "a", "now": NOW, "title": "x"})
    assert s.write(
        "memory/write_findings",
        "citadel_risk",
        {
            "agent": "a",
            "now": NOW,
            "findings": [
                {
                    "kind": "owner_gap",
                    "subject": "system:Auth",
                    "summary": "s",
                    "cites": ["system:Auth"],
                }
            ],
        },
    )
    assert s.read("work/untasked_findings", db_user="citadel_pm")  # PM reads every memory


def test_memory_graph_permissions():
    s = MemoryStore("synthetic")
    lesson = {"agent": "a", "now": NOW, "system": "system:Auth", "text": "t", "cites": ["x"]}
    assert s.write("memory/write_lesson", "citadel_qa", lesson)
    assert s.read("memory/lessons", {}, db_user="citadel_dev")  # developers read QA's lessons
    with pytest.raises(acl.Refused):
        s.write("memory/write_lesson", "citadel_dev", lesson)
    with pytest.raises(acl.Refused):
        s.read("memory/findings", db_user="citadel_dev")


def test_acl_table_renders_setuser_lines():
    lines = acl.setuser_commands("falkordb", {u: "pw" for u in acl.PERMISSIONS})
    risk = next(line for line in lines if " citadel_risk " in line)
    assert risk == (
        "ACL SETUSER citadel_risk on >pw +@all %R~brain_falkordb %R~sim_falkordb_* "
        "%RW~mem_falkordb_risk"
    )
    assert set(acl.ROLE_OF) <= set(acl.PERMISSIONS)


def test_every_named_read_and_write_is_implemented():
    s = MemoryStore("synthetic")
    assert set(s._reads) == set(work_store.READS)
    assert set(s._writes) == set(work_store.WRITES)
