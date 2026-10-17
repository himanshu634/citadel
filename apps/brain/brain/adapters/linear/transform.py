"""Linear transform: raw cache -> canonical records. No network.

Why: everything Linear-specific about turning API JSON into the graph's vocabulary lives here:
issues -> ticket WorkItem, comments -> Comment, team members -> Person + MEMBER_OF, teams -> Team,
and the links between tickets:
- BLOCKS: from `blocks` relations in both directions (this blocks that, other blocks this);
- MENTIONS: from `related` relations, and from attachment URLs (usually a GitHub PR, which the
  loader finds by its `url`). Other relation types (`duplicate`) are ignored.

The uid is the Linear issue id, not the identifier ("IDN-2"): an issue that moves to another team
gets a new identifier but stays one node. People are identified by Linear `displayName` (a name
with "@" in it is skipped: no email addresses in the graph).

Removed tickets: every fetch run returns every open issue of the configured teams, so an issue
whose latest cached copy is open but that is missing from the newest completed run was archived,
deleted or moved out of scope. It is emitted as a canceled tombstone ("Removed from Linear", no
assignees, no links), dated at that run's start so it passes the ingest cursor.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from brain.adapters.base import SourceUnavailable
from brain.adapters.linear.fetch import check_permission
from brain.adapters.runs import completed_pages, nodes, read_json, run_id_of, run_started
from brain.canonical import (
    CLOSED_STATUS,
    CanonicalRecord,
    Comment,
    Link,
    Person,
    Team,
    WorkItem,
    person_uid,
    team_uid,
    url_ref,
)
from brain.config import CompanyConfig

SOURCE = "linear"
MAX_BODY = 20_000  # characters kept per ticket description / comment

# Linear `state.type` -> status_category; any type not listed here counts as "todo".
STATUS_MAP = {
    "triage": "backlog",
    "backlog": "backlog",
    "unstarted": "todo",
    "started": "in_progress",
    "completed": "done",
    "canceled": "canceled",
}
# Linear `priority` -> priority; 0 means "no priority".
PRIORITY_MAP = {0: None, 1: "urgent", 2: "high", 3: "medium", 4: "low"}
REMOVED_STATE = "Removed from Linear"  # state of a tombstone (see the module docstring)


def issue_uid(id: str) -> str:
    return f"linear:issue:{id}"


def _login(user: dict[str, Any] | None) -> str | None:
    """Linear user -> login (displayName); None for a deleted user, a blank name, or a name
    that is an email address (never stored)."""
    name = ((user or {}).get("displayName") or "").strip()
    return name if name and "@" not in name else None


def _latest_issues(folder: Path) -> tuple[dict[str, dict[str, Any]], set[str], str | None]:
    """Read completed pages; for the same issue id keep the most recently updated version.

    Also returns the ids in the newest completed run and that run's id (None: no run yet).
    """
    issues: dict[str, dict[str, Any]] = {}
    pages = completed_pages(folder)
    newest = max((run_id_of(p) for p in pages), default=None)  # ids sort by time
    in_newest: set[str] = set()
    for page in pages:
        is_newest = run_id_of(page) == newest
        for node in read_json(page, []):
            old = issues.get(node["id"])
            if old is None or node["updatedAt"] >= old["updatedAt"]:
                issues[node["id"]] = node
            if is_newest:
                in_newest.add(node["id"])
    return issues, in_newest, newest


def _ticket(node: dict[str, Any]) -> WorkItem:
    assignee = _login(node.get("assignee"))
    return WorkItem(
        uid=issue_uid(node["id"]),
        source=SOURCE,
        url=node["url"],
        kind="ticket",
        number=node["number"],
        key=node["identifier"],
        title=node["title"],
        body=(node.get("description") or "")[:MAX_BODY],
        state=node["state"]["name"],
        status_category=STATUS_MAP.get(node["state"]["type"], "todo"),
        priority=PRIORITY_MAP.get(node.get("priority") or 0),
        due_date=node.get("dueDate"),
        created_at=node["createdAt"],
        updated_at=node["updatedAt"],
        closed_at=node.get("completedAt") or node.get("canceledAt"),
        author_login=_login(node.get("creator")),
        assignees=[assignee] if assignee else [],
        labels=[label["name"] for label in nodes(node.get("labels"))],
        container=node["team"]["key"],
    )


def _removed(ticket: WorkItem, run_id: str) -> WorkItem:
    """Tombstone of a ticket that left Linear (or the configured teams) before run `run_id`."""
    at = run_started(run_id)
    return ticket.model_copy(
        update={
            "state": REMOVED_STATE,
            "status_category": "canceled",
            "assignees": [],
            "updated_at": at,
            "closed_at": at,
        }
    )


def _link(rel: str, from_uid: str, to_uid: str) -> Link:
    return Link(
        rel=rel,
        from_uid=from_uid,
        from_label="WorkItem",
        to_uid=to_uid,
        to_label="WorkItem",
        source=SOURCE,
    )


def _related_ids(node: dict[str, Any]) -> list[str]:
    """Ids of the issues `node` blocks, is blocked by, or relates to."""
    ids = [
        rel["relatedIssue"]["id"]
        for rel in nodes(node.get("relations"))
        if rel["type"] in ("blocks", "related")
    ]
    ids += [
        rel["issue"]["id"] for rel in nodes(node.get("inverseRelations")) if rel["type"] == "blocks"
    ]
    return ids


def ticket_records(node: dict[str, Any], known: Callable[[str], bool]) -> Iterator[CanonicalRecord]:
    """One issue's records: the ticket, its comments and its relation links (BLOCKS, related and
    attachment MENTIONS). `known(id)` says whether an issue id is in the cache; related or
    blocking issues it does not know are the ticket's `unresolved_refs`."""
    ticket = _ticket(node)
    ticket.unresolved_refs = sorted({issue_uid(i) for i in _related_ids(node) if not known(i)})
    yield ticket

    for comment in nodes(node.get("comments")):
        author = _login(comment.get("user"))
        if author is None:
            continue  # deleted user: no one to credit
        yield Comment(
            uid=f"linear:comment:{comment['id']}",
            source=SOURCE,
            url=ticket.url,
            work_item_uid=ticket.uid,
            author_login=author,
            created_at=comment["createdAt"],
            body=(comment.get("body") or "")[:MAX_BODY],
        )

    for rel in nodes(node.get("relations")):
        other = issue_uid(rel["relatedIssue"]["id"])
        if rel["type"] == "blocks":
            yield _link("BLOCKS", ticket.uid, other)
        elif rel["type"] == "related":
            yield _link("MENTIONS", ticket.uid, other)
    for rel in nodes(node.get("inverseRelations")):
        if rel["type"] == "blocks":
            yield _link("BLOCKS", issue_uid(rel["issue"]["id"]), ticket.uid)
    for attachment in nodes(node.get("attachments")):
        if attachment.get("url"):
            yield _link("MENTIONS", ticket.uid, url_ref(attachment["url"]))


def records(company: CompanyConfig, source, cache: Path) -> Iterator[CanonicalRecord]:
    meta = read_json(cache / "meta.json")
    if meta is None:
        raise SourceUnavailable(f"no Linear cache at {cache}; run `make fetch` first")
    check_permission(company)  # again here: the config may have changed since fetch

    for team in read_json(cache / "teams.json", []):
        yield Team(name=team["name"], source=SOURCE)
        team_id = team_uid(team["name"])
        for member in nodes(team.get("members")):
            login = _login(member)
            if login is None:
                continue
            yield Person(login=login, display_name=member.get("name"), source=SOURCE)
            if member.get("active"):
                yield Link(
                    rel="MEMBER_OF",
                    from_uid=person_uid(login),
                    from_label="Person",
                    to_uid=team_id,
                    to_label="Team",
                    source=SOURCE,
                )

    blocks: set[tuple[str, str]] = set()
    mentions: set[tuple[str, str]] = set()
    removed: set[str] = set()  # uids of tombstones: no links to or from them
    issues, in_newest, newest = _latest_issues(cache / "issues")
    for node in issues.values():
        if source.teams and node["team"]["key"] not in source.teams:
            continue  # cached before the team set changed; the next fetch clears it
        ticket = _ticket(node)
        if newest and node["id"] not in in_newest and ticket.status_category not in CLOSED_STATUS:
            removed.add(ticket.uid)
            yield _removed(ticket, newest)
            continue
        for rec in ticket_records(node, lambda id: id in issues):
            if isinstance(rec, Link):
                (blocks if rec.rel == "BLOCKS" else mentions).add((rec.from_uid, rec.to_uid))
            else:
                yield rec

    # Every BLOCKS link on every call: the loader deletes BLOCKS edges of this source that are
    # missing from the load, so leaving one out would delete a real edge. Links that touch a
    # tombstone are left out on purpose (older copies of other issues may still list them).
    for rel, pairs in (("BLOCKS", blocks), ("MENTIONS", mentions)):
        for from_uid, to_uid in sorted(pairs):
            if from_uid not in removed and to_uid not in removed:
                yield _link(rel, from_uid, to_uid)
