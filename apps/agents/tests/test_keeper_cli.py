"""`agents keeper ...` through typer's CliRunner: the ledger is a MemoryKeeperStore, the brain
is FakeBrainFacts, the graph tools are the fake brain. Nothing here calls FalkorDB or the API."""

from __future__ import annotations

import pytest
from agents import cli
from agents.keeper import decide
from agents.keeper.model import gap_uid
from agents.keeper.store import MemoryKeeperStore
from agents.policies import offline_client
from agents.testing import FakeBrainFacts, fake_brain
from brain import config
from typer.testing import CliRunner

SLUG = "synthetic"
KEEPER = "citadel_keeper"
GROUNDED = "What caused the rotation race?"  # the fake brain relates one item: fake:pr:2
NOTICED = {
    "subject": "system:Auth",
    "text": "Auth has no owner.",
    "about": ["system:Auth"],
}

runner = CliRunner()


@pytest.fixture
def env(monkeypatch):
    store, brain = MemoryKeeperStore(SLUG), FakeBrainFacts()
    monkeypatch.setattr(cli, "_keeper_store", lambda slug: store)
    monkeypatch.setattr(cli, "_keeper_graph_run", lambda: fake_brain)
    monkeypatch.setattr(cli, "connected", lambda: None)
    monkeypatch.setattr(decide, "DEFAULT_BRAIN", brain)
    return store, brain


def keeper(*args: str):
    return runner.invoke(cli.app, ["keeper", *args])


def seed_gap(store, text: str = GROUNDED) -> str:
    [row] = store.write(
        "ledger/open_gap",
        "citadel_brain",
        {"uid": gap_uid(), "kind": "failed_question", "text": text, "norm": text.lower(),
         "now": "2026-10-17T09:00:00Z"},
    )  # fmt: skip
    return row["uid"]


def seed_claim(store, status: str = "pending_approval", gap: str | None = None) -> str:
    uid = f"claim:{len(store.claims):012d}"
    store.write(
        "ledger/write_claim",
        KEEPER,
        {"uid": uid, "kind": "owner", "subject": "system:Auth", "statement": "Alice owns Auth.",
         "value": "person:alice", "about": ["system:Auth"], "evidence": ["fake:pr:2"],
         "status": status, "author": "keeper", "gap": gap, "now": "2026-10-17T09:30:00Z"},
    )  # fmt: skip
    return uid


def no_key(monkeypatch) -> None:
    monkeypatch.setattr(config, "get_settings", lambda: config.Settings(anthropic_api_key=""))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_review_offline_prints_done(env):
    store, _ = env
    seed_gap(store)
    result = keeper("review", SLUG, "--offline")
    assert result.exit_code == 0, result.output
    lines = result.output.strip().splitlines()
    assert lines[0].startswith("start") and lines[-1].startswith("done")
    assert store.reviews[-1].state == "done" and store.reviews[-1].budget == 5


def test_review_budget_option(env):
    store, _ = env
    result = keeper("review", SLUG, "--offline", "--budget", "0")
    assert result.exit_code == 0, result.output
    assert store.reviews[-1].budget == 0


def test_review_without_key_skips(env, monkeypatch):
    store, brain = env
    no_key(monkeypatch)
    brain.notices = {"unowned_hot_system": [NOTICED]}
    result = keeper("review", SLUG)
    assert result.exit_code == 0, result.output
    assert "review skipped: no API key (use --offline)" in result.output
    [r] = store.reviews
    assert (r.state, r.stop) == ("skipped", "no_api_key")
    assert "review_skipped" in [e.action for e in store.log]
    assert [g.subject for g in store.gaps.values()] == ["system:Auth"]  # notice ran, no LLM job
    assert not store.consults


def test_review_with_key_in_environment_runs(env, monkeypatch):
    store, _ = env
    no_key(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(cli, "_keeper_client_for", lambda offline: offline_client)
    result = keeper("review", SLUG)  # a key in the environment counts: not skipped
    assert result.exit_code == 0, result.output
    assert "review skipped" not in result.output and store.reviews[-1].state == "done"


def test_notice_prints_new_gaps(env):
    store, brain = env
    brain.notices = {"unowned_hot_system": [NOTICED]}
    result = keeper("notice", SLUG)
    assert result.exit_code == 0, result.output
    [gap] = store.gaps.values()
    assert gap.uid in result.output and "Auth has no owner." in result.output
    again = keeper("notice", SLUG)
    assert "no new gaps" in again.output


def test_gaps_filters_by_status(env):
    store, _ = env
    open_gap = seed_gap(store)
    done = seed_gap(store, "Other question?")
    store.write("ledger/set_gap_status", KEEPER, {"uid": done, "from": ["open"], "to": "resolved",
                                                  "now": "2026-10-17T10:00:00Z"})  # fmt: skip
    every = keeper("gaps", SLUG)
    assert open_gap in every.output and done in every.output
    only = keeper("gaps", SLUG, "--status", "resolved")
    assert done in only.output and open_gap not in only.output
    assert keeper("gaps", SLUG, "--status", "bogus").exit_code != 0


def test_claims_lists_claims(env):
    store, _ = env
    uid = seed_claim(store)
    result = keeper("claims", SLUG, "--status", "pending_approval")
    assert result.exit_code == 0 and uid in result.output and "Alice owns Auth." in result.output
    assert uid not in keeper("claims", SLUG, "--status", "accepted").output


def test_log_newest_first_with_limit(env):
    store, _ = env
    seed_gap(store)
    keeper("review", SLUG, "--offline")
    result = keeper("log", SLUG, "--limit", "2")
    assert result.exit_code == 0, result.output
    lines = result.output.strip().splitlines()
    assert len(lines) == 2 and "review_done" in lines[0]


def test_approve_accepts_pending_claim(env):
    store, _ = env
    uid = seed_claim(store)
    result = keeper("approve", SLUG, uid, "--by", "ana", "--why", "checked")
    assert result.exit_code == 0, result.output
    assert store.claims[uid].status == "accepted" and store.claims[uid].approved_by == "ana"


def test_reject_rejects_pending_claim(env):
    store, _ = env
    uid = seed_claim(store)
    result = keeper("reject", SLUG, uid, "--by", "ana")
    assert result.exit_code == 0, result.output
    assert store.claims[uid].status == "rejected"


def test_approve_not_pending_exit_1(env):
    store, _ = env
    uid = seed_claim(store, "accepted")
    result = keeper("approve", SLUG, uid, "--by", "ana")
    assert result.exit_code == 1
    assert "not waiting for approval" in result.output
    assert keeper("reject", SLUG, uid, "--by", "ana").exit_code == 1


def test_approve_needs_by(env):
    store, _ = env
    assert keeper("approve", SLUG, seed_claim(store)).exit_code != 0
