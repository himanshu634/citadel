"""Resumable paged fetching: runs, checkpoints and which pages count as complete."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from brain.adapters.runs import completed_pages, fetch_paged, read_json, write_json

WINDOW = datetime(2024, 1, 1, tzinfo=UTC)


def page(nodes: list[dict], cursor: str | None, more: bool) -> dict[str, Any]:
    return {"x": {"nodes": nodes, "pageInfo": {"hasNextPage": more, "endCursor": cursor}}}


class FakeClient:
    """Serves canned pages in order; an Exception instance in the list is raised instead."""

    def __init__(self, pages: list[Any]) -> None:
        self.pages = list(pages)
        self.calls: list[tuple[str, dict]] = []

    def query(self, name: str, variables: dict[str, Any]) -> dict:
        self.calls.append((name, dict(variables)))
        item = self.pages.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def fetch(client: FakeClient, folder: Path, **kwargs) -> int:
    return fetch_paged(
        client,
        "things",
        {"owner": "o"},
        lambda d: d["x"],
        folder,
        WINDOW,
        log=lambda m: None,
        **kwargs,
    )


def test_fetch_paged_writes_pages_and_completes_run(tmp_path):
    client = FakeClient([page([{"id": 1}], "c1", True), page([{"id": 2}], "c2", False)])

    assert fetch(client, tmp_path) == 2

    files = sorted(tmp_path.glob("*_*.json"))
    assert [read_json(f) for f in files] == [[{"id": 1}], [{"id": 2}]]
    state = read_json(tmp_path / "state.json")
    assert len(state["completed_runs"]) == 1
    assert state["run"] is None
    assert state["complete_until"] is not None
    assert completed_pages(tmp_path) == files


def test_unfinished_run_is_resumed_from_its_cursor(tmp_path):
    first = FakeClient([page([{"id": 1}], "c1", True), RuntimeError("rate limited")])
    with pytest.raises(RuntimeError):
        fetch(first, tmp_path)
    assert [c[1]["after"] for c in first.calls] == [None, "c1"]

    second = FakeClient([page([{"id": 2}], "c2", False)])
    assert fetch(second, tmp_path) == 1

    assert [c[1]["after"] for c in second.calls] == ["c1"]
    state = read_json(tmp_path / "state.json")
    assert len(state["completed_runs"]) == 1
    assert len(completed_pages(tmp_path)) == 2  # page 1 from the first call, page 2 from the resume


def test_completed_pages_skip_unfinished_runs(tmp_path):
    # run ids have one-second resolution, so seed the finished run by hand under an older id
    write_json(tmp_path / "20240101T000000_0000.json", [{"id": 1}])
    write_json(
        tmp_path / "state.json",
        {"complete_until": "2024-01-01T00:00:00Z", "completed_runs": ["20240101T000000"]},
    )
    done = completed_pages(tmp_path)

    broken = FakeClient([page([{"id": 2}], "c2", True), RuntimeError("stopped")])
    with pytest.raises(RuntimeError):
        fetch(broken, tmp_path)

    assert len(list(tmp_path.glob("*_*.json"))) == 2  # the half-finished run left a page behind
    assert completed_pages(tmp_path) == done == [tmp_path / "20240101T000000_0000.json"]


def test_send_since_passes_run_lower_bound(tmp_path):
    sent = FakeClient([page([{"id": 1}], None, False)])
    fetch(sent, tmp_path / "sent")
    assert sent.calls[0][1]["since"] == "2024-01-01T00:00:00Z"

    quiet = FakeClient([page([{"id": 1}], None, False)])
    fetch(quiet, tmp_path / "quiet", send_since=False)
    assert "since" not in quiet.calls[0][1]
