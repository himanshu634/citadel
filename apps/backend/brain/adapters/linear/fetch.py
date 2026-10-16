"""Linear fetch: network -> raw cache. Resumable and incremental.

Why: Linear data is fetched once and cached as raw JSON, so the transform (and tests) can re-run
with no API calls. Layout under data/raw/<slug>/linear/<workspace>/:

    meta.json                  {urlKey, name, fetched_at} of the workspace the key belongs to,
                               plus issue_teams: the team keys the issue runs were fetched for
    teams.json                 the configured teams with their members, as returned
    issues/
        state.json             {"complete_until": ..., "completed_runs": [...], "run": {...}}
        <run>_<page>.json      one raw page of issues each

Issues are fetched in resumable runs; see brain.adapters.runs for how runs and checkpoints work.
When the team set changes, issues/ is cleared so the next run covers the whole window for the new
set (an incremental run would miss a newly added team's older tickets).
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from brain.adapters.linear.client import LinearClient, LinearError
from brain.adapters.linear.source import LinearSource
from brain.adapters.runs import PagedClient, fetch_paged, iso, read_json, write_json
from brain.config import CompanyConfig

PAGE_SIZE = 25  # issues per page; each carries capped relations and comments, so keep it small


def check_permission(company: CompanyConfig) -> None:
    """Hard rule: Linear workspaces are private, so only `own` (or `synthetic`) data is ingested."""
    if company.data_permission not in ("own", "synthetic"):
        raise PermissionError(
            f"Linear workspaces are private; set data_permission: own in "
            f"companies/{company.slug}.yaml only if this is your own data"
        )


def fetch_meta(client: PagedClient, source: LinearSource, cache: Path) -> dict[str, Any]:
    """Name the workspace the API key belongs to and refuse if it is not the configured one.
    Keeps `issue_teams` from the previous meta.json (run() updates it)."""
    org = client.query("meta", {})["viewer"]["organization"]
    if org["urlKey"] != source.workspace:
        raise RuntimeError(
            f"the Linear API key belongs to workspace {org['urlKey']!r}, "
            f"but the company config says {source.workspace!r}"
        )
    meta = {"urlKey": org["urlKey"], "name": org["name"], "fetched_at": iso(datetime.now(UTC))}
    previous = read_json(cache / "meta.json") or {}
    if "issue_teams" in previous:
        meta["issue_teams"] = previous["issue_teams"]
    write_json(cache / "meta.json", meta)
    return meta


def fetch_teams(client: PagedClient, source: LinearSource, cache: Path) -> list[dict[str, Any]]:
    """Snapshot of the configured teams (all of them when none are configured)."""
    teams = client.query("teams", {})["teams"]["nodes"]
    if source.teams:
        missing = sorted(set(source.teams) - {t["key"] for t in teams})
        if missing:
            raise LinearError(
                f"team key(s) {', '.join(missing)} not found in Linear workspace "
                f"{source.workspace!r}"
            )
        teams = [t for t in teams if t["key"] in source.teams]
    write_json(cache / "teams.json", teams)
    return teams


def run(
    company: CompanyConfig,
    source: LinearSource,
    cache: Path,
    client: PagedClient | None = None,
    log=print,
) -> None:
    check_permission(company)  # before any data is pulled
    cache.mkdir(parents=True, exist_ok=True)
    if client is None:
        with LinearClient(log=log) as own_client:
            return run(company, source, cache, own_client, log)

    meta = fetch_meta(client, source, cache)
    keys = [t["key"] for t in fetch_teams(client, source, cache)]
    issues = cache / "issues"
    if issues.exists() and meta.get("issue_teams") != sorted(keys):
        log(f"  issues: team set changed to {', '.join(sorted(keys))}; fetching the whole window")
        shutil.rmtree(issues)
    write_json(cache / "meta.json", {**meta, "issue_teams": sorted(keys)})  # after the clear
    window_start = datetime.combine(company.window.since, datetime.min.time(), tzinfo=UTC)
    fetch_paged(
        client,
        "issues",
        {"teams": keys, "first": PAGE_SIZE},
        lambda d: d["issues"],
        issues,
        window_start,
        log=log,
    )
