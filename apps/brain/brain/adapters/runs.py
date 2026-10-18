"""Resumable, incremental paging of GraphQL connections into a raw JSON cache.

Why: every source that pages through an API needs the same thing: a half-finished fetch (rate
limit, Ctrl-C) must resume where it stopped, and a repeat fetch must only go back as far as the
last one. Paged lists are fetched in "runs". A run that stops halfway resumes from its saved
cursor. Only pages from completed runs are read by a transform (`completed_pages`), so a
half-finished fetch can never make ingest skip older records. The next run only goes back to the
previous run's start (minus a margin), which makes repeat fetches cheap.

The state also remembers the window the completed runs were fetched under (`window_start`).
When the company's `window.since` moves earlier, the next run starts at the new window start
instead of the last run's start, so the older records it now covers are fetched too; a state
without a stored window (written before it was recorded) is treated the same way, once. `full`
ignores the last run's start as well.

Layout of one list's folder:

    state.json                 {"complete_until": ..., "completed_runs": [...], "run": {...},
                                "window_start": ...}
    <run>_<page>.json          one raw page of nodes each

Any client with a `query(name, variables)` method works (`PagedClient`), so GitHub and Linear
share this code.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

OVERLAP = timedelta(hours=1)  # re-fetch a little before the last run's start, to be safe
RUN_ID_FORMAT = "%Y%m%dT%H%M%S"  # a run's id is its start time (UTC), so ids sort by time


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
    full: bool = False,
    log=print,
) -> int:
    """Fetch every page of one GraphQL connection into `folder`, resuming an unfinished run.

    `connection` picks the connection out of the response. If `stop_when_older` names a node
    timestamp field, paging stops once a page reaches nodes older than the run's lower bound
    (used for newest-first lists that have no server-side `since` filter; those also set
    `send_since=False` because their query declares no $since). `incremental=False` always
    starts at the window and keeps only the newest completed run (used for commit history,
    whose dates come from client clocks, so "since the last run" could miss late pushes).
    A new run starts at the last run's start (minus `OVERLAP`) only when the cached runs cover
    `window_start` (see `covers_window`) and `full` is not set; otherwise at `window_start`.
    Returns the number of pages written in this call.
    """
    state = read_json(folder / "state.json", {"complete_until": None, "completed_runs": []})
    run = state.get("run")
    if run is None:
        lower = window_start
        if incremental and not full and state["complete_until"]:
            if covers_window(state, window_start):
                lower = max(lower, parse_ts(state["complete_until"]) - OVERLAP)
            else:
                log(
                    f"  {folder.name}: the cached runs start at "
                    f"{state.get('window_start') or 'an unknown date'}, the window now at "
                    f"{iso(window_start)}; fetching the whole window"
                )
        started = datetime.now(UTC)
        run = {
            "id": started.strftime(RUN_ID_FORMAT),
            "started": iso(started),
            "lower": iso(lower),
            "window_start": iso(window_start),
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
        page_nodes = conn["nodes"]
        write_json(folder / f"{run['id']}_{run['page']:04d}.json", page_nodes)
        written += 1
        run["page"] += 1
        run["cursor"] = conn["pageInfo"]["endCursor"]
        state["run"] = run
        write_json(folder / "state.json", state)  # checkpoint after every page

        reached_bottom = stop_when_older and any(
            parse_ts(n[stop_when_older]) < lower for n in page_nodes
        )
        if not conn["pageInfo"]["hasNextPage"] or reached_bottom or not page_nodes:
            break

    if not incremental:  # this run covers the whole window: older runs are redundant
        for old in folder.glob("*_*.json"):
            if run_id_of(old) != run["id"]:
                old.unlink()
        state["completed_runs"] = []
    state["completed_runs"].append(run["id"])
    state["complete_until"] = run["started"]
    # The window this run was started under, not today's: a window widened while the run was
    # unfinished is not covered yet, so the next run starts at the window. A run started before
    # the window was recorded leaves it unknown, and the next run also starts at the window.
    state["window_start"] = run.get("window_start")
    state["run"] = None
    write_json(folder / "state.json", state)
    log(f"  {folder.name}: {written} pages")
    return written


def covers_window(state: dict[str, Any], window_start: datetime) -> bool:
    """Whether the completed runs in `state` reach back to `window_start`: the window they were
    fetched under starts there or earlier. A state without a stored window (written before it
    was recorded, or completed by a run started then) does not: how far back it goes is not
    known, so the next run fetches the whole window once and records it."""
    stored = state.get("window_start")
    return stored is not None and parse_ts(stored) <= window_start


def run_id_of(page: Path) -> str:
    """The run a page belongs to (`<run>_<page>.json`); run ids sort by start time."""
    return page.name.split("_")[0]


def completed_pages(folder: Path) -> list[Path]:
    """Pages from completed runs only, oldest run first (later runs hold newer data)."""
    state = read_json(folder / "state.json", {"completed_runs": []})
    done = set(state["completed_runs"])
    return sorted(p for p in folder.glob("*_*.json") if run_id_of(p) in done)


def unfinished(folder: Path) -> str | None:
    """Why `completed_pages(folder)` is not everything the source holds for the window: no run
    has completed yet (the list was never fetched, or its first run stopped), or a run is still
    in progress (it stopped before its last page and will resume). None when every run is
    complete. An adapter's `incomplete` hook builds on this, so ingest keeps its cursor until
    the missing pages are in: moved past them, it would skip them as already seen."""
    state = read_json(folder / "state.json", {"completed_runs": [], "run": None})
    run = state.get("run")
    if run is not None:
        return f"{folder.name}: fetch run {run['id']} stopped at page {run['page']}"
    if not state["completed_runs"]:
        return f"{folder.name}: not fetched yet"
    return None


def completed_nodes(folder: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    """(run id, node) for every node of every completed page, oldest run first."""
    for page in completed_pages(folder):
        run_id = run_id_of(page)
        for node in json.loads(page.read_text()):
            yield run_id, node


def run_started(run_id: str) -> datetime:
    """When run `run_id` started (UTC)."""
    return datetime.strptime(run_id, RUN_ID_FORMAT).replace(tzinfo=UTC)


def nodes(conn: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The `nodes` of a GraphQL connection; [] when the connection or its nodes are null."""
    return (conn or {}).get("nodes") or []
