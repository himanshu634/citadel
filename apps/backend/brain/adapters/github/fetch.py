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

Paged lists are fetched in "runs". A run that stops halfway (rate limit, Ctrl-C) resumes from
its saved cursor. Only pages from completed runs are read by the transform, so a half-finished
fetch can never make ingest skip older records. The next run only goes back to the previous
run's start (minus a margin), which makes repeat fetches cheap.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from brain.adapters.github.client import GithubClient, graphql, token
from brain.config import CompanyConfig
from brain.normalize import glob_match

OVERLAP = timedelta(hours=1)  # re-fetch a little before the last run's start, to be safe
DOC_SUFFIXES = (".md", ".mdx")
MAX_DOCS = 300
CODEOWNERS_PATHS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def read_json(path: Path, default: Any = None) -> Any:
    return json.loads(path.read_text()) if path.exists() else default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)  # atomic: a crash never leaves half a file


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


# --- resumable paged lists --------------------------------------------------------------------


def fetch_paged(
    client: GithubClient,
    query: str,
    variables: dict[str, Any],
    connection: Callable[[dict], dict],
    folder: Path,
    window_start: datetime,
    stop_when_older: str | None = None,
    send_since: bool = True,
    log=print,
) -> int:
    """Fetch every page of one GraphQL connection into `folder`, resuming an unfinished run.

    `connection` picks the connection out of the response. If `stop_when_older` names a node
    timestamp field, paging stops once a page reaches nodes older than the run's lower bound
    (used for newest-first lists that have no server-side `since` filter; those also set
    `send_since=False` because their query declares no $since).
    Returns the number of pages written in this call.
    """
    state = read_json(folder / "state.json", {"complete_until": None, "completed_runs": []})
    run = state.get("run")
    if run is None:
        lower = window_start
        if state["complete_until"]:
            lower = max(lower, parse_ts(state["complete_until"]) - OVERLAP)
        started = datetime.now(UTC)
        run = {
            "id": started.strftime("%Y%m%dT%H%M%S"),
            "started": iso(started),
            "lower": iso(lower),
            "cursor": None,
            "page": 0,
        }
    else:
        log(f"  resuming {folder.name} run {run['id']} at page {run['page']}")
    lower = parse_ts(run["lower"])

    written = 0
    while True:
        page_vars = {**variables, "after": run["cursor"]}
        if send_since:
            page_vars["since"] = run["lower"]
        data = client.query(query, page_vars)
        conn = connection(data)
        nodes = conn["nodes"]
        write_json(folder / f"{run['id']}_{run['page']:04d}.json", nodes)
        written += 1
        run["page"] += 1
        run["cursor"] = conn["pageInfo"]["endCursor"]
        state["run"] = run
        write_json(folder / "state.json", state)  # checkpoint after every page

        reached_bottom = stop_when_older and any(
            parse_ts(n[stop_when_older]) < lower for n in nodes
        )
        if not conn["pageInfo"]["hasNextPage"] or reached_bottom or not nodes:
            break

    state["completed_runs"].append(run["id"])
    state["complete_until"] = run["started"]
    state["run"] = None
    write_json(folder / "state.json", state)
    log(f"  {folder.name}: {written} pages")
    return written


def completed_pages(folder: Path) -> list[Path]:
    """Pages from completed runs only, oldest run first (later runs hold newer data)."""
    state = read_json(folder / "state.json", {"completed_runs": []})
    done = set(state["completed_runs"])
    return sorted(p for p in folder.glob("*_*.json") if p.name.split("_")[0] in done)


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


# --- the whole fetch --------------------------------------------------------------------------


def run(company: CompanyConfig, source, cache: Path, log=print) -> None:
    owner, name = source.repo.split("/")
    include = set(source.include)
    cache.mkdir(parents=True, exist_ok=True)
    client = GithubClient(log=log)
    window_start = datetime.combine(company.window.since, datetime.min.time(), tzinfo=UTC)

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
            log=log,
        )
        log(f"  commits: {write_commits(repo, branch, window_start, cache)} since window")

    wanted = []
    if "codeowners" in include:
        wanted += [p for p in CODEOWNERS_PATHS if p in set(paths)]
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
