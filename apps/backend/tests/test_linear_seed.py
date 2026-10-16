"""Seeding a Linear workspace from the synthetic tickets: guards, order, resume, CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from brain import cli
from brain.adapters.linear import seed as seed_mod
from brain.adapters.linear.client import LinearError
from brain.adapters.linear.seed import SeedReport, load_seed, seed
from brain.adapters.linear.source import LinearSource
from brain.adapters.runs import read_json
from brain.config import CompanyConfig
from typer.testing import CliRunner

TICKETS = Path(__file__).parents[1] / "examples" / "synthetic_company" / "tickets"
STATE_TYPES = ["backlog", "unstarted", "started", "completed", "canceled"]


def company(permission: str = "synthetic", aliases: dict | None = None) -> CompanyConfig:
    return CompanyConfig.model_validate(
        {
            "slug": "lin_seed",
            "name": "Linear seed",
            "data_permission": permission,
            "window": {"since": "2026-01-01"},
            "sources": [],
            "people": {"aliases": aliases or {}},
        }
    )


SOURCE = LinearSource.model_validate({"type": "linear", "workspace": "acme", "teams": ["IDN"]})


def lookup(teams=("IDN", "PAY"), users=("alice", "bob", "carol", "erin"), url_key="acme") -> dict:
    return {
        "viewer": {"organization": {"urlKey": url_key}},
        "teams": {
            "nodes": [
                {
                    "id": f"team-{k}",
                    "key": k,
                    "states": {
                        "nodes": [
                            # lowest position per type must win: a decoy at a higher position
                            {"id": f"{k}-{t}-late", "type": t, "position": 9}
                            for t in STATE_TYPES
                        ]
                        + [
                            {"id": f"{k}-{t}", "type": t, "position": i}
                            for i, t in enumerate(STATE_TYPES)
                        ]
                    },
                }
                for k in teams
            ]
        },
        "users": {
            "nodes": [{"id": f"user-{u}", "displayName": u, "active": True} for u in users]
            + [{"id": "user-gone", "displayName": "dave", "active": False}]
        },
    }


class FakeClient:
    """Records every call; answers the lookup and hands out ids for mutations."""

    def __init__(self, lookup_data: dict | None = None, fail_on_issue: int | None = None) -> None:
        self.lookup = lookup_data or lookup()
        self.fail_on_issue = fail_on_issue
        self.calls: list[tuple[str, dict]] = []
        self.issues_created = 0

    @property
    def mutations(self) -> list[tuple[str, dict]]:
        return [c for c in self.calls if c[0] != "seed_lookup"]

    def query(self, name: str, variables: dict[str, Any]) -> dict:
        self.calls.append((name, variables))
        if name == "seed_lookup":
            return self.lookup
        if name == "issue_create":
            self.issues_created += 1
            if self.issues_created == self.fail_on_issue:
                raise LinearError("boom")
            n = self.issues_created
            return {"issueCreate": {"success": True, "issue": {"id": f"id-{n}", "identifier": n}}}
        if name == "relation_create":
            return {"issueRelationCreate": {"success": True}}
        return {"attachmentCreate": {"success": True}}


def seed_it(client, state: Path, comp=None, src=SOURCE) -> SeedReport:
    return seed(client, comp or company(), src, load_seed(TICKETS), state, log=lambda m: None)


def names(client: FakeClient) -> list[str]:
    return [n for n, _ in client.mutations]


def test_load_seed_counts():
    data = load_seed(TICKETS)

    assert len(data.tickets) == 10
    assert len(data.blocks) == 4 and ("IDN-1", "IDN-2") in data.blocks
    assert len(data.attachments) == 4
    assert (
        "PAY-3",
        "https://example.com/synthetic/app/pull/9",
        "feat(billing): usage-based add-ons",
    ) in (data.attachments)
    assert data.teams == {"IDN": "Identity", "PAY": "Payments"}


def test_refuses_non_synthetic_company(tmp_path):
    client = FakeClient()

    with pytest.raises(PermissionError, match="synthetic"):
        seed_it(client, tmp_path / "s.json", company("own"))

    assert client.calls == []


def test_refuses_other_workspace(tmp_path):
    client = FakeClient(lookup(url_key="other"))

    with pytest.raises(LinearError, match="other.*acme|acme.*other"):
        seed_it(client, tmp_path / "s.json")

    assert client.mutations == []


def test_missing_team_or_user_reported_before_any_write(tmp_path):
    client = FakeClient(lookup(teams=("PAY",), users=("alice", "bob", "carol")))

    with pytest.raises(LinearError) as err:
        seed_it(client, tmp_path / "s.json")

    assert client.mutations == []
    assert "create team IDN (Identity)" in str(err.value)
    assert "erin" in str(err.value)
    assert "dave" not in str(err.value)  # inactive users are only a problem when assigned


def test_inactive_assignee_counts_as_missing(tmp_path):
    data = load_seed(TICKETS)
    data.tickets[0].assignees = ["dave"]
    client = FakeClient()

    with pytest.raises(LinearError, match="dave"):
        seed(client, company(), SOURCE, data, tmp_path / "s.json", log=lambda m: None)

    assert client.mutations == []


def test_aliases_are_reversed_to_find_the_linear_user(tmp_path):
    client = FakeClient(lookup(users=("Alice A", "bob", "carol", "erin")))

    seed_it(client, tmp_path / "s.json", company(aliases={"Alice A": "alice"}))

    first = next(
        v
        for n, v in client.mutations
        if n == "issue_create" and v["input"]["title"] == "Rotate JWT signing keys"
    )
    assert first["input"]["assigneeId"] == "user-Alice A"


def test_creates_issues_relations_attachments(tmp_path):
    client = FakeClient()

    report = seed_it(client, tmp_path / "s.json")

    assert report == SeedReport(created=18, skipped=0)
    assert (
        names(client) == ["issue_create"] * 10 + ["relation_create"] * 4 + ["attachment_create"] * 4
    )
    pay3 = next(
        v["input"]
        for n, v in client.mutations
        if n == "issue_create" and v["input"]["title"] == "Usage-based add-ons"
    )
    assert pay3["stateId"] == "PAY-started"
    assert pay3["priority"] == 3
    assert pay3["dueDate"] == "2026-10-30"
    assert pay3["teamId"] == "team-PAY"
    assert pay3["assigneeId"] == "user-erin"
    assert pay3["createdAt"].endswith("Z")
    done = next(
        v["input"]
        for n, v in client.mutations
        if n == "issue_create" and v["input"]["title"] == "Extract token service"
    )
    assert done["stateId"] == "IDN-completed"
    # a blocker blocks: IDN-1 (id-1) blocks IDN-2 (id-2)
    relation = next(v["input"] for n, v in client.mutations if n == "relation_create")
    assert relation == {"issueId": "id-1", "relatedIssueId": "id-2", "type": "blocks"}
    attachment = next(v["input"] for n, v in client.mutations if n == "attachment_create")
    assert attachment["url"].startswith("https://example.com/synthetic/")


def test_no_priority_maps_to_zero_and_no_due_date_is_omitted(tmp_path):
    data = load_seed(TICKETS)
    data.tickets[0].priority = None
    client = FakeClient()

    seed(client, company(), SOURCE, data, tmp_path / "s.json", log=lambda m: None)

    first = client.mutations[0][1]["input"]
    assert first["priority"] == 0 and "dueDate" not in first


def test_rerun_creates_nothing(tmp_path):
    state = tmp_path / "s.json"
    seed_it(FakeClient(), state)
    again = FakeClient()

    report = seed_it(again, state)

    assert again.mutations == []
    assert report == SeedReport(created=0, skipped=18)


def test_resumes_after_failure(tmp_path):
    state = tmp_path / "s.json"
    broken = FakeClient(fail_on_issue=3)

    with pytest.raises(LinearError, match="boom"):
        seed_it(broken, state)

    saved = read_json(state)
    assert sorted(saved["issues"]) == ["IDN-1", "IDN-2"]
    resumed = FakeClient()

    report = seed_it(resumed, state)

    assert names(resumed).count("issue_create") == 8
    assert report.created == 16 and report.skipped == 2
    final = read_json(state)
    assert len(final["issues"]) == 10 and len(final["relations"]) == 4
    assert len(final["attachments"]) == 4


def test_a_mutation_answering_failure_raises(tmp_path):
    client = FakeClient()
    client.query_orig = client.query

    def bad(name, variables):
        out = client.query_orig(name, variables)
        return {"issueCreate": {"success": False, "issue": None}} if name == "issue_create" else out

    client.query = bad

    with pytest.raises(LinearError, match="issue_create"):
        seed_it(client, tmp_path / "s.json")


def test_cli_without_yes_writes_nothing(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("seed must not run without --yes")

    monkeypatch.setattr(seed_mod, "seed", boom)

    result = CliRunner().invoke(cli.app, ["linear-seed", "synthetic_linear"])

    assert result.exit_code == 0, result.output
    assert "synthetic-co" in result.output
    assert "10 tickets" in result.output and "4 blocks" in result.output
    assert "4 attachments" in result.output


def test_cli_fails_cleanly_without_a_linear_source():
    result = CliRunner().invoke(cli.app, ["linear-seed", "synthetic"])

    assert result.exit_code == 1
    assert "linear" in result.output.lower()
