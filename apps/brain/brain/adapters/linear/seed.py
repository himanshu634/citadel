"""Copy the synthetic tickets into a real Linear workspace.

Why: the offline synthetic tickets (JSONL) and the live adapter must give the same answers, and
the only way to show that is a real Linear workspace holding the same tickets. This is the one
place the project writes to Linear. It refuses anything but a `synthetic` company, checks the
workspace, teams and users before the first write, and keeps a state file (written after each
mutation) so a stopped run resumes without creating a ticket twice.

State file, data/raw/<slug>/linear/<workspace>/seed_state.json:

    {"issues": {"IDN-1": "<linear id>"}, "relations": ["IDN-1>IDN-2"],
     "attachments": ["PAY-3 <url>"]}

A crash between a mutation and its state write can still leave one duplicate in Linear; delete
it by hand. So can a retry: LinearClient retries 5xx, so a 502/504 that came back after Linear had
already committed an issueCreate creates the ticket a second time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from brain.adapters.linear.client import LinearError
from brain.adapters.linear.source import LinearSource
from brain.adapters.runs import PagedClient, iso, read_json, write_json
from brain.canonical import Link, WorkItem
from brain.config import CompanyConfig

STATE_TYPE = {  # canonical status category -> Linear workflow state type
    "backlog": "backlog",
    "todo": "unstarted",
    "in_progress": "started",
    "done": "completed",
    "canceled": "canceled",
}
PRIORITY = {"urgent": 1, "high": 2, "medium": 3, "low": 4, None: 0}


@dataclass
class SeedData:
    tickets: list[WorkItem]
    blocks: list[tuple[str, str]] = field(default_factory=list)  # (blocker key, blocked key)
    attachments: list[tuple[str, str, str]] = field(default_factory=list)  # (key, url, title)
    teams: dict[str, str] = field(default_factory=dict)  # team key -> name


@dataclass
class SeedReport:
    created: int
    skipped: int


def _lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_seed(tickets_dir: Path) -> SeedData:
    """Read the synthetic `tickets/` folder. An attachment takes its url and title from the base
    work item (a PR or issue) that a MENTIONS link points to; the base file sits one folder up."""
    tickets = [WorkItem.model_validate(r) for r in _lines(tickets_dir / "work_items.jsonl")]
    key_of = {t.uid: t.key for t in tickets}
    base = {
        r["uid"]: WorkItem.model_validate(r)
        for r in _lines(tickets_dir.parent / "work_items.jsonl")
    }
    data = SeedData(tickets=tickets)
    for rec in _lines(tickets_dir / "links.jsonl"):
        link = Link.model_validate(rec)
        if link.rel == "BLOCKS" and link.from_uid in key_of and link.to_uid in key_of:
            data.blocks.append((key_of[link.from_uid], key_of[link.to_uid]))
        elif link.rel == "MENTIONS" and link.from_uid in key_of and link.to_uid in base:
            target = base[link.to_uid]
            data.attachments.append((key_of[link.from_uid], target.url or "", target.title))
    teams = read_json(tickets_dir / "linear_seed.json", {}).get("teams", {})
    data.teams = dict(teams)
    return data


def _mutate(client: PagedClient, name: str, field_name: str, payload: dict[str, Any]) -> dict:
    out = client.query(name, {"input": payload})[field_name]
    if not out.get("success"):
        raise LinearError(f"Linear refused {name}: {payload.get('title') or payload}")
    return out


def _first_state_ids(team: dict[str, Any]) -> dict[str, str]:
    """Workflow state type -> id of the state of that type with the lowest position."""
    best: dict[str, dict[str, Any]] = {}
    for state in team["states"]["nodes"]:
        old = best.get(state["type"])
        if old is None or state["position"] < old["position"]:
            best[state["type"]] = state
    return {kind: s["id"] for kind, s in best.items()}


def _linear_names(login: str, aliases: dict[str, str]) -> list[str]:
    """Display names a login may carry in Linear: itself, then every alias that maps to it."""
    return [login] + [name for name, target in aliases.items() if target == login]


def _check_lookup(
    lookup: dict[str, Any], company: CompanyConfig, source: LinearSource, data: SeedData
) -> tuple[dict[str, dict], dict[str, dict[str, str]], dict[str, str]]:
    """Return (team key -> team, team key -> state type -> state id, login -> user id), or
    raise one error listing every gap."""
    url_key = lookup["viewer"]["organization"]["urlKey"]
    if url_key != source.workspace:
        raise LinearError(
            f"the Linear API key belongs to workspace {url_key!r}, "
            f"but the company config says {source.workspace!r}"
        )
    teams = {t["key"]: t for t in lookup["teams"]["nodes"]}
    states = {key: _first_state_ids(team) for key, team in teams.items()}
    users = {u["displayName"]: u["id"] for u in lookup["users"]["nodes"] if u["active"]}

    problems = [
        f"create team {key} ({name})" for key, name in data.teams.items() if key not in teams
    ]
    for ticket in data.tickets:
        team = teams.get(ticket.container or "")
        if team is None:
            if ticket.container not in data.teams:
                problems.append(f"ticket {ticket.key} is in unknown team {ticket.container}")
            continue
        if STATE_TYPE[ticket.status_category] not in states[team["key"]]:
            problems.append(f"team {team['key']} has no {STATE_TYPE[ticket.status_category]} state")

    logins: dict[str, str] = {}
    for login in sorted({a for t in data.tickets for a in t.assignees or []}):
        found = next(
            (users[n] for n in _linear_names(login, company.people.aliases) if n in users), None
        )
        if found is None:
            problems.append(f"create or activate user {login}")
        else:
            logins[login] = found
    if problems:
        raise LinearError(
            f"Linear workspace {source.workspace!r} is not ready:\n  " + "\n  ".join(problems)
        )
    return teams, states, logins


def seed(
    client: PagedClient,
    company: CompanyConfig,
    source: LinearSource,
    data: SeedData,
    state_path: Path,
    log=print,
) -> SeedReport:
    """Create the missing tickets, blocking relations and PR attachments, in that order."""
    if company.data_permission != "synthetic":
        raise PermissionError(
            f"linear-seed writes to Linear, so it only runs for data_permission: synthetic "
            f"(companies/{company.slug}.yaml has {company.data_permission})"
        )
    lookup = client.query("seed_lookup", {})
    teams, states, logins = _check_lookup(lookup, company, source, data)

    state = read_json(state_path, {})
    issues: dict[str, str] = state.setdefault("issues", {})
    relations: list[str] = state.setdefault("relations", [])
    attachments: list[str] = state.setdefault("attachments", [])
    report = SeedReport(created=0, skipped=0)

    def done(kind: str, what: str) -> None:
        write_json(state_path, state)  # after every mutation, so a stop loses nothing
        report.created += 1
        log(f"  {kind} {what}")

    for ticket in data.tickets:
        if ticket.key in issues:
            report.skipped += 1
            continue
        payload: dict[str, Any] = {
            "teamId": teams[ticket.container]["id"],
            "title": ticket.title,
            "stateId": states[ticket.container][STATE_TYPE[ticket.status_category]],
            "priority": PRIORITY[ticket.priority],
            "createdAt": iso(ticket.created_at),
        }
        if ticket.body:
            payload["description"] = ticket.body
        if ticket.assignees:
            payload["assigneeId"] = logins[ticket.assignees[0]]
        if ticket.due_date:
            payload["dueDate"] = ticket.due_date.isoformat()
        out = _mutate(client, "issue_create", "issueCreate", payload)
        issues[ticket.key] = out["issue"]["id"]
        done("issue", ticket.key)

    for blocker, blocked in data.blocks:
        tag = f"{blocker}>{blocked}"
        if tag in relations:
            report.skipped += 1
            continue
        payload = {"issueId": issues[blocker], "relatedIssueId": issues[blocked], "type": "blocks"}
        _mutate(client, "relation_create", "issueRelationCreate", payload)
        relations.append(tag)
        done("blocks", tag)

    for key, url, title in data.attachments:
        tag = f"{key} {url}"
        if tag in attachments:
            report.skipped += 1
            continue
        payload = {"issueId": issues[key], "url": url, "title": title}
        _mutate(client, "attachment_create", "attachmentCreate", payload)
        attachments.append(tag)
        done("attachment", tag)
    return report
