"""GitHub fetch: network -> raw cache. Resumable and incremental.

Why: GitHub data is fetched once and cached as raw JSON pages, so the transform (and tests) can
re-run with no API calls. Layout under data/raw/<slug>/github/<owner>__<name>/:

    meta.json                  repo visibility + default branch (checked against data_permission)
    pull_requests/ issues/ history/
        state.json             {"complete_until": ..., "completed_runs": [...], "run": {...}}
        <run>_<page>.json      one raw GraphQL page each
    repo.git/                  partial clone (commits + trees, no file contents)
    commits.jsonl              `git log --name-only` since the window (no emails)
    tree.txt                   every file path at HEAD (for path mentions and doc discovery)
    blobs/<path>               text of CODEOWNERS and markdown docs
    blobs.json                 [{path, updated_at}] for those files

Paged lists (pull_requests/, issues/, history/) are fetched in resumable runs; see
brain.adapters.runs for how runs, checkpoints and completed pages work.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from brain.adapters.github.client import GithubClient, graphql, token
from brain.adapters.runs import fetch_paged, iso, unfinished, write_json
from brain.config import CompanyConfig
from brain.normalize import glob_match

DOC_SUFFIXES = (".md", ".mdx")
MAX_DOCS = 300
CODEOWNERS_PATHS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")


# --- repo meta / permission ----------------------------------------------------------------


def check_permission(meta: dict[str, Any], company: CompanyConfig) -> None:
    """Hard rule: a private repo is only ingested when the company declares `own` data."""
    if meta["isPrivate"] and company.data_permission != "own":
        raise PermissionError(
            f"{meta['nameWithOwner']} is private; set data_permission: own in "
            f"companies/{company.slug}.yaml only if this is your own data"
        )


def fetch_meta(client: GithubClient, owner: str, name: str, cache: Path) -> dict[str, Any]:
    repo = client.query("repo_meta", {"owner": owner, "name": name})["repository"]
    if repo is None:
        raise RuntimeError(f"repository {owner}/{name} not found (or no access)")
    meta = {
        "nameWithOwner": repo["nameWithOwner"],
        "url": repo["url"],
        "isPrivate": repo["isPrivate"],
        "defaultBranch": (repo["defaultBranchRef"] or {}).get("name") or "main",
        "fetched_at": iso(datetime.now(UTC)),
    }
    write_json(cache / "meta.json", meta)
    return meta


# --- git: commits and file tree ---------------------------------------------------------------


def _git(*args: str, cwd: Path | None = None, input: str | None = None) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, input=input, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {out.stderr.strip()[:300]}")
    return out.stdout


def _auth_args(private: bool) -> list[str]:
    """For private repos, pass the token as an HTTP header for this one command only."""
    if not private:
        return []
    import base64

    basic = base64.b64encode(f"x-access-token:{token()}".encode()).decode()
    return ["-c", f"http.extraHeader=Authorization: Basic {basic}"]


def sync_clone(meta: dict[str, Any], cache: Path, log=print) -> Path:
    """Partial clone (commits and trees, no blobs) of the default branch, or update it."""
    repo = cache / "repo.git"
    branch = meta["defaultBranch"]
    auth = _auth_args(meta["isPrivate"])
    if not repo.exists():
        log(f"  cloning {meta['url']} (partial, no file contents)")
        _git(
            *auth,
            "clone",
            "--bare",
            "--filter=blob:none",
            "--single-branch",
            "--branch",
            branch,
            f"{meta['url']}.git",
            str(repo),
        )
    else:
        _git(
            *auth,
            "fetch",
            "--filter=blob:none",
            "origin",
            f"+refs/heads/{branch}:refs/heads/{branch}",
            cwd=repo,
        )
    return repo


def write_commits(repo: Path, branch: str, since: datetime, cache: Path) -> int:
    """`git log` since the window -> commits.jsonl. Author *name* only: never the email.

    --no-renames keeps git from downloading file contents to detect renames.
    """
    sep_rec, sep_field = "\x1e", "\x1f"
    out = _git(
        "log",
        branch,
        f"--since={iso(since)}",
        "--no-merges",
        "--no-renames",
        "--name-only",
        f"--format={sep_rec}%H{sep_field}%an{sep_field}%cI{sep_field}%s",
        cwd=repo,
    )
    rows = []
    for block in out.split(sep_rec)[1:]:
        header, _, files = block.partition("\n")
        sha, author_name, committed, subject = header.split(sep_field)
        rows.append(
            {
                "sha": sha,
                "author_name": author_name,
                "committed_at": committed,
                "subject": subject,
                "files": [f for f in files.splitlines() if f],
            }
        )
    with (cache / "commits.jsonl").open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return len(rows)


def write_tree(repo: Path, branch: str, cache: Path) -> list[str]:
    paths = _git("ls-tree", "-r", "--name-only", branch, cwd=repo).splitlines()
    (cache / "tree.txt").write_text("\n".join(paths) + "\n")
    return paths


def last_changed(repo: Path, branch: str, paths: list[str]) -> dict[str, str]:
    """Last commit date per path, from one `git log` pass (newest first, first hit wins)."""
    if not paths:
        return {}
    out = _git(
        "log", branch, "--no-renames", "--name-only", "--format=\x1e%cI", "--", *paths, cwd=repo
    )
    dates: dict[str, str] = {}
    for block in out.split("\x1e")[1:]:
        when, _, files = block.partition("\n")
        for f in files.splitlines():
            if f:
                dates.setdefault(f, when.strip())
    return dates


# --- blobs: CODEOWNERS and docs ---------------------------------------------------------------


def pick_docs(paths: list[str], company: CompanyConfig) -> list[str]:
    ignore = company.systems.ignore
    docs = [
        p
        for p in paths
        if p.lower().endswith(DOC_SUFFIXES) and not any(glob_match(p, g) for g in ignore)
    ]
    return docs[:MAX_DOCS]


def fetch_blobs(
    client: GithubClient, owner: str, name: str, branch: str, paths: list[str], cache: Path
) -> dict[str, str]:
    """Download file texts with batched GraphQL `object(expression:)` aliases, 50 per query."""
    template = graphql("blobs")
    texts: dict[str, str] = {}
    for i in range(0, len(paths), 50):
        batch = paths[i : i + 50]
        fields = "\n    ".join(
            f"f{j}: object(expression: {json.dumps(f'{branch}:{p}')}) "
            "{ ... on Blob { text isBinary isTruncated } }"
            for j, p in enumerate(batch)
        )
        data = client.query(
            "blobs",
            {"owner": owner, "name": name},
            document=template.replace("__BLOB_FIELDS__", fields),
        )
        for j, p in enumerate(batch):
            blob = data["repository"].get(f"f{j}") or {}
            if blob.get("text") is not None and not blob.get("isBinary"):
                texts[p] = blob["text"]
    for p, text in texts.items():
        dest = cache / "blobs" / p
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)
    return texts


# --- what the cache still lacks ---------------------------------------------------------------


def incomplete(source, cache: Path) -> str | None:
    """What `records` cannot read yet: a paged list the source includes with no completed run or
    one still unfinished (see runs.unfinished). Only pull_requests/ and issues/ count: their
    items carry GitHub's timestamps, which the ingest cursor filters, and one cursor covers both
    lists. history/ does not: its run always covers the whole window again, and commits are
    dated by client clocks, so the cursor never filters them."""
    include = set(source.include)
    lists = []
    if include & {"pull_requests", "reviews"}:
        lists.append("pull_requests")
    if "issues" in include:
        lists.append("issues")
    reasons = [reason for name in lists if (reason := unfinished(cache / name))]
    return "; ".join(reasons) or None


# --- the whole fetch --------------------------------------------------------------------------


def run(company: CompanyConfig, source, cache: Path, full: bool = False, log=print) -> None:
    """The whole fetch. `full` makes every paged run start at the window (see
    brain.adapters.runs.fetch_paged)."""
    owner, name = source.repo.split("/")
    include = set(source.include)
    cache.mkdir(parents=True, exist_ok=True)
    client = GithubClient(log=log)
    window_start = company.window.start

    meta = fetch_meta(client, owner, name, cache)
    check_permission(meta, company)  # before any data is pulled
    repo_vars = {"owner": owner, "name": name}

    if include & {"pull_requests", "reviews"}:
        fetch_paged(
            client,
            "pull_requests",
            repo_vars,
            lambda d: d["repository"]["pullRequests"],
            cache / "pull_requests",
            window_start,
            stop_when_older="updatedAt",
            send_since=False,
            full=full,
            log=log,
        )
    if "issues" in include:
        fetch_paged(
            client,
            "issues",
            repo_vars,
            lambda d: d["repository"]["issues"],
            cache / "issues",
            window_start,
            full=full,
            log=log,
        )

    branch = meta["defaultBranch"]
    if include & {"commits", "codeowners", "repo_docs"}:
        repo = sync_clone(meta, cache, log=log)
        paths = write_tree(repo, branch, cache)
    else:
        paths = []
    if "commits" in include:
        fetch_paged(
            client,
            "history",
            repo_vars,
            lambda d: d["repository"]["defaultBranchRef"]["target"]["history"],
            cache / "history",
            window_start,
            incremental=False,  # commit dates are client clocks: always re-read the window
            log=log,
        )
        log(f"  commits: {write_commits(repo, branch, window_start, cache)} since window")

    wanted = []
    if "codeowners" in include:
        present = set(paths)
        wanted += [p for p in CODEOWNERS_PATHS if p in present]
    docs = pick_docs(paths, company) if "repo_docs" in include else []
    wanted += docs
    if wanted:
        texts = fetch_blobs(client, owner, name, branch, wanted, cache)
        dates = last_changed(repo, branch, docs)
        write_json(
            cache / "blobs.json",
            [{"path": p, "updated_at": dates.get(p)} for p in wanted if p in texts],
        )
        log(f"  blobs: {len(texts)} files (CODEOWNERS + docs)")
