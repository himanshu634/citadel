"""Sources routes: where a company's graph comes from, and the leftover sync records.

Why: the Sources page answers "is each source being read, and what did it give the graph?". The
YAML says what is configured, each adapter's `check` says what would stop the next build (a missing
folder, no token), the SyncState nodes say when each source was last loaded, and the nodes' own
`source` labels say what is in the graph. Node counts are per label, not per configured source:
two folders of one type write the same label, so the page says they are counted together.

A SyncState whose key is no longer configured is a leftover (a source removed, or a folder that
moved). Removing one deletes only that cursor record, never the nodes.
"""

from __future__ import annotations

from typing import Annotated, Any

from brain import db, pipeline
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.companies import Runner, StartLock, read_config
from backend.api.deps import company_slug
from backend.api.models import KindCount, LabelCounts, SourceRow, SourcesOut, SyncRecord
from backend.jobs import ACTIVE

router = APIRouter(prefix="/companies/{slug}", tags=["sources"])
Slug = Annotated[str, Depends(company_slug)]


def _location(config: Any) -> tuple[str, list[str]]:
    """What a source reads, as the YAML names it, and its parts (GitHub include, Linear teams)."""
    if repo := getattr(config, "repo", None):
        return repo, list(getattr(config, "include", []))
    if workspace := getattr(config, "workspace", None):
        return workspace, list(getattr(config, "teams", None) or [])
    if path := getattr(config, "path", None):
        return path.as_posix(), []
    return config.type, []


def _row(source: pipeline.ConfiguredSource, state: dict | None, since: str) -> SourceRow:
    location, reads = _location(source.config)
    problem = source.problem
    if problem is not None:
        status = "blocked" if problem.blocks else "skipped"
    else:
        status = "synced" if state else "never"
    state = state or {}
    return SourceRow(
        key=source.key,
        type=source.config.type,
        location=location,
        reads=reads,
        downloads=source.downloads,
        status=status,
        problem=problem.message if problem else None,
        last_run=state.get("last_run"),
        records=state.get("records"),
        cursor=state.get("cursor"),
        window_changed=bool(state) and state.get("window_since") != since,
    )


def _labels(rows: list[dict]) -> list[LabelCounts]:
    """Fold `sources/nodes_by_source` rows into one entry per label: a count per node label, and
    per work item kind with its states."""
    groups: dict[str, dict[tuple[str, str | None], KindCount]] = {}
    for r in rows:
        kinds = groups.setdefault(r["source"], {})
        key = (r["label"], r["kind"])
        entry = kinds.setdefault(key, KindCount(label=r["label"], kind=r["kind"], count=0))
        entry.count += r["n"]
        if r["state"] is not None:
            entry.states[r["state"]] = entry.states.get(r["state"], 0) + r["n"]
    out = [
        LabelCounts(
            source=source,
            total=sum(k.count for k in kinds.values()),
            kinds=sorted(kinds.values(), key=lambda k: -k.count),
        )
        for source, kinds in groups.items()
    ]
    return sorted(out, key=lambda g: -g.total)


@router.get("/sources")
def get_sources(slug: Slug) -> SourcesOut:
    cfg = read_config(slug)
    since = cfg.window.since.isoformat()
    configured = pipeline.configured_sources(slug)
    built = db.graph_exists(slug)
    states = db.run(slug, "load/sync_state_list", read_only=True) if built else []
    counts = db.run(slug, "sources/nodes_by_source", read_only=True) if built else []
    by_key = {s["key"]: s for s in states}
    keys = {s.key for s in configured}
    return SourcesOut(
        slug=slug,
        since=since,
        built=built,
        sources=[_row(s, by_key.get(s.key), since) for s in configured],
        labels=_labels(counts),
        leftovers=[
            SyncRecord(
                key=s["key"],
                adapter=s["adapter"],
                last_run=s["last_run"],
                records=s["records"],
                cursor=s["cursor"],
            )
            for s in states
            if s["key"] not in keys
        ],
    )


@router.delete("/sources/leftovers", status_code=204)
def forget_leftover(
    slug: Slug, runner: Runner, lock: StartLock, key: Annotated[str, Query(min_length=1)]
) -> None:
    """Delete one leftover sync record. 409 when the key is still configured or a build of this
    company is running (it could write the record again); 404 when there is no such record."""
    read_config(slug)
    if key in set(pipeline.planned_sources(slug)[1]):
        raise HTTPException(status_code=409, detail=f"{key} is still a source of {slug}")
    with lock:  # no build can start between the check and the delete
        if (snap := runner.current(slug)) is not None and snap.state in ACTIVE:
            raise HTTPException(
                status_code=409, detail=f"A build of {slug} is running; try again when it ends"
            )
        removed = (
            db.run(slug, "load/sync_state_forget", {"key": key})[0]["removed"]
            if db.graph_exists(slug)
            else 0
        )
    if not removed:
        raise HTTPException(status_code=404, detail=f"{slug} has no sync record {key}")
