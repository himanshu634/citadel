"""Resumable, incremental paging of GraphQL connections into a raw JSON cache.

Why: every source that pages through an API needs the same thing: a half-finished fetch (rate
limit, Ctrl-C) must resume where it stopped, and a repeat fetch must only go back as far as the
last one. Paged lists are fetched in "runs". A run that stops halfway resumes from its saved
cursor. Only pages from completed runs are read by a transform (`completed_pages`), so a
half-finished fetch can never make ingest skip older records. The next run only goes back to the
previous run's start (minus a margin), which makes repeat fetches cheap.

Layout of one list's folder:

    state.json                 {"complete_until": ..., "completed_runs": [...], "run": {...}}
    <run>_<page>.json          one raw page of nodes each

Any client with a `query(name, variables)` method works (`PagedClient`), so GitHub and Linear
share this code.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

OVERLAP = timedelta(hours=1)  # re-fetch a little before the last run's start, to be safe


class PagedClient(Protocol):
    def query(self, name: str, variables: dict[str, Any]) -> dict: ...


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


def fetch_paged(
    client: PagedClient,
    query: str,
    variables: dict[str, Any],
    connection: Callable[[dict], dict],
    folder: Path,
    window_start: datetime,
    stop_when_older: str | None = None,
    send_since: bool = True,
    incremental: bool = True,
    log=print,
) -> int:
    """Fetch every page of one GraphQL connection into `folder`, resuming an unfinished run.

    `connection` picks the connection out of the response. If `stop_when_older` names a node
    timestamp field, paging stops once a page reaches nodes older than the run's lower bound
    (used for newest-first lists that have no server-side `since` filter; those also set
    `send_since=False` because their query declares no $since). `incremental=False` always
    starts at the window and keeps only the newest completed run (used for commit history,
    whose dates come from client clocks, so "since the last run" could miss late pushes).
    Returns the number of pages written in this call.
    """
    state = read_json(folder / "state.json", {"complete_until": None, "completed_runs": []})
    run = state.get("run")
    if run is None:
        lower = window_start
        if incremental and state["complete_until"]:
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

    if not incremental:  # this run covers the whole window: older runs are redundant
        for old in folder.glob("*_*.json"):
            if run_id_of(old) != run["id"]:
                old.unlink()
        state["completed_runs"] = []
    state["completed_runs"].append(run["id"])
    state["complete_until"] = run["started"]
    state["run"] = None
    write_json(folder / "state.json", state)
    log(f"  {folder.name}: {written} pages")
    return written


def run_id_of(page: Path) -> str:
    """The run a page belongs to (`<run>_<page>.json`); run ids sort by start time."""
    return page.name.split("_")[0]


def completed_pages(folder: Path) -> list[Path]:
    """Pages from completed runs only, oldest run first (later runs hold newer data)."""
    state = read_json(folder / "state.json", {"completed_runs": []})
    done = set(state["completed_runs"])
    return sorted(p for p in folder.glob("*_*.json") if run_id_of(p) in done)
