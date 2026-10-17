"""GitHub transform: raw cache -> canonical records. No network.

Why: everything GitHub-specific about turning API JSON into the graph's vocabulary lives here:
PRs and issues -> WorkItem, reviews -> Review, comments -> Comment, commits -> Change,
CODEOWNERS -> Ownership, markdown files -> Document, and the links between them:
- PART_OF: commit -> PR, from the PR's commit list, its merge commit, or "(#123)" in the subject;
- CLOSES: PR -> issue, from `closingIssuesReferences`;
- MENTIONS: "#123" / PR URLs in bodies and docs, and repo paths ("src/index/") -> System.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from brain.adapters.base import SourceUnavailable, first_heading
from brain.adapters.github import codeowners
from brain.adapters.github.fetch import check_permission
from brain.adapters.runs import completed_nodes, nodes, read_json
from brain.canonical import (
    CanonicalRecord,
    Change,
    Comment,
    Document,
    Link,
    Ownership,
    Review,
    WorkItem,
    system_uid,
)
from brain.config import CompanyConfig
from brain.normalize import system_for_path

SOURCE = "github"
MAX_BODY = 20_000  # characters kept per PR/issue/comment body
MAX_DOC = 50_000
SUBJECT_PR_RE = re.compile(r"\(#(\d+)\)\s*$")
HASH_REF_RE = re.compile(r"(?<![\w/&#])#(\d+)\b")
PATH_REF_RE = re.compile(r"(?<![\w/.:-])((?:[\w.-]+/)+[\w.-]*)")


def actor_login(actor: dict[str, Any] | None) -> str | None:
    """GitHub actor -> login. Bots get a "[bot]" suffix so they are flagged as bots."""
    if not actor or not actor.get("login"):
        return None  # deleted account ("ghost")
    login = actor["login"]
    if actor.get("__typename") == "Bot" and not login.endswith("[bot]"):
        login += "[bot]"
    return login


class Repo:
    """uid and url helpers for one repository."""

    def __init__(self, name_with_owner: str, url: str, branch: str) -> None:
        self.name, self.url, self.branch = name_with_owner, url, branch

    def pr(self, n: int) -> str:
        return f"github:{self.name}:pr:{n}"

    def issue(self, n: int) -> str:
        return f"github:{self.name}:issue:{n}"

    def commit(self, sha: str) -> str:
        return f"github:{self.name}:commit:{sha}"

    def doc(self, path: str) -> str:
        return f"github:{self.name}:doc:{path}"


def _latest_by_number(folder: Path) -> dict[int, dict[str, Any]]:
    """Read completed pages; for the same number keep the most recently updated version."""
    items: dict[int, dict[str, Any]] = {}
    for _, node in completed_nodes(folder):
        old = items.get(node["number"])
        if old is None or node["updatedAt"] >= old["updatedAt"]:
            items[node["number"]] = node
    return items


def _comments(repo: Repo, work_uid: str, conn: dict[str, Any] | None) -> Iterator[Comment]:
    """A PR's or issue's comments; those by deleted accounts are skipped."""
    for c in nodes(conn):
        if login := actor_login(c["author"]):
            yield Comment(
                uid=f"github:{repo.name}:comment:{c['id']}",
                source=SOURCE,
                url=c["url"],
                work_item_uid=work_uid,
                author_login=login,
                created_at=c["createdAt"],
                body=(c["body"] or "")[:MAX_BODY],
            )


class PathIndex:
    """Which strings in text are real repo paths, and which system each maps to."""

    def __init__(self, tree: list[str], company: CompanyConfig) -> None:
        self.files = set(tree)
        self.dirs = {"/".join(p.split("/")[:i]) for p in tree for i in range(1, p.count("/") + 1)}
        self.systems = company.systems

    def systems_in(self, text: str) -> set[str]:
        found = set()
        for raw in PATH_REF_RE.findall(text or ""):
            path = raw.rstrip(".,:;)").rstrip("/")
            if path in self.files:
                hit = system_for_path(path, self.systems)
            elif path in self.dirs:
                hit = system_for_path(path + "/__file__", self.systems)
            else:
                continue
            if hit:
                found.add(hit[0])
        return found


def records(company: CompanyConfig, source, cache: Path) -> Iterator[CanonicalRecord]:
    meta = read_json(cache / "meta.json")
    if meta is None:
        raise SourceUnavailable(f"no GitHub cache at {cache}; run `make fetch` first")
    check_permission(meta, company)  # again here: the config may have changed since fetch
    include = set(source.include)
    repo = Repo(meta["nameWithOwner"], meta["url"], meta["defaultBranch"])
    tree_file = cache / "tree.txt"
    tree = tree_file.read_text().splitlines() if tree_file.exists() else []
    paths = PathIndex(tree, company)

    want_prs = bool(include & {"pull_requests", "reviews"})
    prs = _latest_by_number(cache / "pull_requests") if want_prs else {}
    issues = _latest_by_number(cache / "issues") if "issues" in include else {}
    number_uid = {n: repo.issue(n) for n in issues} | {n: repo.pr(n) for n in prs}
    url_ref_re = re.compile(rf"github\.com/{re.escape(repo.name)}/(?:pull|issues)/(\d+)")

    def mentions(from_uid: str, from_label: str, text: str, skip: set[str]) -> Iterator[Link]:
        targets = {int(m) for m in HASH_REF_RE.findall(text or "")}
        targets |= {int(m) for m in url_ref_re.findall(text or "")}
        for n in sorted(targets):
            uid = number_uid.get(n)
            if uid and uid != from_uid and uid not in skip:
                yield Link(
                    rel="MENTIONS",
                    from_uid=from_uid,
                    from_label=from_label,
                    to_uid=uid,
                    to_label="WorkItem",
                    source=SOURCE,
                )
        for name in sorted(paths.systems_in(text)):
            yield Link(
                rel="MENTIONS",
                from_uid=from_uid,
                from_label=from_label,
                to_uid=system_uid(name),
                to_label="System",
                source=SOURCE,
            )

    # --- pull requests, their reviews, comments, closes and commits --------------------------
    commit_pr: dict[str, int] = {}  # commit sha -> PR number
    for n, pr in prs.items():
        uid = repo.pr(n)
        state = "merged" if pr["mergedAt"] else pr["state"].lower()
        if "pull_requests" in include:
            yield WorkItem(
                uid=uid,
                source=SOURCE,
                url=pr["url"],
                kind="pull_request",
                number=n,
                title=pr["title"],
                body=(pr["body"] or "")[:MAX_BODY],
                state=state,
                created_at=pr["createdAt"],
                updated_at=pr["updatedAt"],
                closed_at=pr["closedAt"],
                merged_at=pr["mergedAt"],
                author_login=actor_login(pr["author"]),
                labels=[lb["name"] for lb in nodes(pr["labels"])],
                container=repo.name,
            )
            closes = set()
            for ref in nodes(pr["closingIssuesReferences"]):
                if ref["repository"]["nameWithOwner"] == repo.name and ref["number"] in issues:
                    closes.add(repo.issue(ref["number"]))
                    yield Link(
                        rel="CLOSES",
                        from_uid=uid,
                        from_label="WorkItem",
                        to_uid=repo.issue(ref["number"]),
                        to_label="WorkItem",
                        source=SOURCE,
                    )
            yield from mentions(uid, "WorkItem", pr["body"], skip=closes)
            yield from _comments(repo, uid, pr["comments"])
            for node in nodes(pr["commits"]):
                commit_pr.setdefault(node["commit"]["oid"], n)
            if pr["mergeCommit"]:
                commit_pr[pr["mergeCommit"]["oid"]] = n
        if "reviews" in include:
            for r in nodes(pr["reviews"]):
                login = actor_login(r["author"])
                if login and r["submittedAt"] and r["state"] != "PENDING":
                    yield Review(
                        uid=f"github:{repo.name}:review:{r['id']}",
                        source=SOURCE,
                        url=r["url"],
                        work_item_uid=uid,
                        reviewer_login=login,
                        state=r["state"],
                        submitted_at=r["submittedAt"],
                    )

    # --- issues -----------------------------------------------------------------------------
    for n, it in issues.items():
        uid = repo.issue(n)
        yield WorkItem(
            uid=uid,
            source=SOURCE,
            url=it["url"],
            kind="issue",
            number=n,
            title=it["title"],
            body=(it["body"] or "")[:MAX_BODY],
            state=it["state"].lower(),
            created_at=it["createdAt"],
            updated_at=it["updatedAt"],
            closed_at=it["closedAt"],
            author_login=actor_login(it["author"]),
            labels=[lb["name"] for lb in nodes(it["labels"])],
            container=repo.name,
        )
        yield from mentions(uid, "WorkItem", it["body"], skip=set())
        yield from _comments(repo, uid, it["comments"])

    # --- commits ----------------------------------------------------------------------------
    commits_file = cache / "commits.jsonl"
    if "commits" in include and commits_file.exists():
        logins: dict[str, str | None] = {}
        for _, node in completed_nodes(cache / "history"):
            user = (node["author"] or {}).get("user") or {}
            logins[node["oid"]] = user.get("login")
        aliases = company.people.aliases
        for line in commits_file.read_text().splitlines():
            row = json.loads(line)
            name = row["author_name"]
            login = (
                logins.get(row["sha"])
                or aliases.get(name)
                or (name if name.endswith("[bot]") else None)
            )
            yield Change(
                uid=repo.commit(row["sha"]),
                source=SOURCE,
                url=f"{repo.url}/commit/{row['sha']}",
                sha=row["sha"],
                date=row["committed_at"],
                author_login=login,
                subject=row["subject"],
                files=row["files"],
            )
            pr_number = commit_pr.get(row["sha"])
            if pr_number is None and (m := SUBJECT_PR_RE.search(row["subject"])):
                pr_number = int(m.group(1))
            if pr_number in prs:
                yield Link(
                    rel="PART_OF",
                    from_uid=repo.commit(row["sha"]),
                    from_label="Change",
                    to_uid=repo.pr(pr_number),
                    to_label="WorkItem",
                    source=SOURCE,
                )

    # --- CODEOWNERS and docs ----------------------------------------------------------------
    blobs = read_json(cache / "blobs.json", [])
    for i, blob in enumerate(blobs):
        path, text = blob["path"], (cache / "blobs" / blob["path"]).read_text()
        url = f"{repo.url}/blob/{repo.branch}/{path}"
        if path.endswith("CODEOWNERS"):
            if "codeowners" in include:
                yield from _ownerships(repo, url, i, text, tree, company)
            continue
        uid = repo.doc(path)
        yield Document(
            uid=uid,
            source=SOURCE,
            url=url,
            path=path,
            title=_doc_title(path, text),
            body=text[:MAX_DOC],
            updated_at=blob["updated_at"],
        )
        yield from mentions(uid, "Document", text, skip=set())


def _ownerships(
    repo: Repo, url: str, i: int, text: str, tree: list[str], company: CompanyConfig
) -> Iterator[Ownership]:
    """CODEOWNERS lines -> Ownership with explicit systems (from the files each pattern covers).

    Catch-all default owners (`*`) and patterns that match no file are skipped.
    """
    for j, (pattern, kind, owner) in enumerate(codeowners.parse(text)):
        if codeowners.is_catch_all(pattern):
            continue
        systems = {
            hit[0]
            for f in codeowners.matching_files(pattern, tree)
            if (hit := system_for_path(f, company.systems))
        }
        if systems:
            yield Ownership(
                uid=f"github:{repo.name}:codeowners:{i}:{j}",
                source=SOURCE,
                url=url,
                owner_kind=kind,
                owner=owner,
                pattern=pattern,
                systems=sorted(systems),
            )


def _doc_title(path: str, text: str) -> str:
    heading = first_heading(text)
    return heading if heading is not None else path
