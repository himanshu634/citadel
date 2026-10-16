"""Linear transform: raw cache -> canonical records. No network.

Why: everything Linear-specific about turning API JSON into the graph's vocabulary lives here:
issues -> ticket WorkItem, comments -> Comment, team members -> Person + MEMBER_OF, teams -> Team,
and the links between tickets:
- BLOCKS: from `blocks` relations in both directions (this blocks that, other blocks this);
- MENTIONS: from `related` relations, and from attachment URLs (usually a GitHub PR, which the
  loader finds by its `url`). Other relation types (`duplicate`) are ignored.

The uid is the Linear issue id, not the identifier ("IDN-2"): an issue that moves to another team
gets a new identifier but stays one node. People are identified by Linear `displayName`.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from brain.adapters.linear.fetch import check_permission
from brain.adapters.runs import completed_pages, read_json
from brain.canonical import CanonicalRecord, Comment, Link, Person, Team, WorkItem, url_ref
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


def issue_uid(id: str) -> str:
    return f"linear:issue:{id}"


def _nodes(conn: dict[str, Any] | None) -> list[dict[str, Any]]:
    return (conn or {}).get("nodes") or []


def _login(user: dict[str, Any] | None) -> str | None:
    """Linear user -> login (displayName); None for a deleted user or a blank name."""
    name = ((user or {}).get("displayName") or "").strip()
    return name or None


def _latest_issues(folder: Path) -> dict[str, dict[str, Any]]:
    """Read completed pages; for the same issue id keep the most recently updated version."""
    issues: dict[str, dict[str, Any]] = {}
    for page in completed_pages(folder):
        for node in read_json(page, []):
            old = issues.get(node["id"])
            if old is None or node["updatedAt"] >= old["updatedAt"]:
                issues[node["id"]] = node
    return issues


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
        labels=[label["name"] for label in _nodes(node.get("labels"))],
        container=node["team"]["key"],
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


def records(company: CompanyConfig, source, cache: Path) -> Iterator[CanonicalRecord]:
    from brain.adapters.base import SourceUnavailable  # local: avoid an import cycle

    meta = read_json(cache / "meta.json")
    if meta is None:
        raise SourceUnavailable(f"no Linear cache at {cache}; run `make fetch` first")
    check_permission(company)  # again here: the config may have changed since fetch

    for team in read_json(cache / "teams.json", []):
        yield Team(name=team["name"], source=SOURCE)
        for member in _nodes(team.get("members")):
            login = _login(member)
            if login is None:
                continue
            yield Person(login=login, display_name=member.get("name"), source=SOURCE)
            if member.get("active"):
                yield Link(
                    rel="MEMBER_OF",
                    from_uid=Person(login=login).uid,
                    from_label="Person",
                    to_uid=Team(name=team["name"]).uid,
                    to_label="Team",
                    source=SOURCE,
                )

    blocks: set[tuple[str, str]] = set()
    mentions: set[tuple[str, str]] = set()
    for node in _latest_issues(cache / "issues").values():
        ticket = _ticket(node)
        yield ticket

        for comment in _nodes(node.get("comments")):
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

        for rel in _nodes(node.get("relations")):
            other = issue_uid(rel["relatedIssue"]["id"])
            if rel["type"] == "blocks":
                blocks.add((ticket.uid, other))
            elif rel["type"] == "related":
                mentions.add((ticket.uid, other))
        for rel in _nodes(node.get("inverseRelations")):
            if rel["type"] == "blocks":
                blocks.add((issue_uid(rel["issue"]["id"]), ticket.uid))
        for attachment in _nodes(node.get("attachments")):
            if attachment.get("url"):
                mentions.add((ticket.uid, url_ref(attachment["url"])))

    # Every BLOCKS link on every call: the loader deletes BLOCKS edges of this source that are
    # missing from the load, so leaving one out would delete a real edge.
    for from_uid, to_uid in sorted(blocks):
        yield _link("BLOCKS", from_uid, to_uid)
    for from_uid, to_uid in sorted(mentions):
        yield _link("MENTIONS", from_uid, to_uid)
