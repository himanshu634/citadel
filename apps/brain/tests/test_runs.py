"""Resumable paged fetching: runs, checkpoints and which pages count as complete."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from brain.adapters.runs import (
    OVERLAP,
    completed_pages,
    fetch_paged,
    parse_ts,
    read_json,
    write_json,
)

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


def fetch(client: FakeClient, folder: Path, window_start: datetime = WINDOW, **kwargs) -> int:
    return fetch_paged(
        client,
        "things",
        {"owner": "o"},
        lambda d: d["x"],
        folder,
        window_start,
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


def test_next_run_resumes_from_complete_until_when_window_unchanged(tmp_path):
    fetch(FakeClient([page([{"id": 1}], None, False)]), tmp_path)
    done = read_json(tmp_path / "state.json")["complete_until"]

    again = FakeClient([page([{"id": 2}], None, False)])
    fetch(again, tmp_path)

    lower = parse_ts(again.calls[0][1]["since"])
    assert lower == parse_ts(done) - OVERLAP  # not the window: an incremental run
    assert read_json(tmp_path / "state.json")["window_start"] == "2024-01-01T00:00:00Z"


def test_widened_window_refetches_from_the_new_start(tmp_path):
    fetch(FakeClient([page([{"id": 1}], None, False)]), tmp_path)  # window: 2024-01-01

    earlier = datetime(2023, 6, 1, tzinfo=UTC)
    client = FakeClient([page([{"id": 0}], None, False)])
    fetch(client, tmp_path, window_start=earlier)

    assert client.calls[0][1]["since"] == "2023-06-01T00:00:00Z"  # the whole widened window
    state = read_json(tmp_path / "state.json")
    assert state["window_start"] == "2023-06-01T00:00:00Z"
    assert len(state["completed_runs"]) == 2

    # the window stays the same (or moves later): incremental again
    again = FakeClient([page([{"id": 3}], None, False)])
    fetch(again, tmp_path, window_start=earlier)
    assert parse_ts(again.calls[0][1]["since"]) == parse_ts(state["complete_until"]) - OVERLAP
    state = read_json(tmp_path / "state.json")
    later = FakeClient([page([{"id": 4}], None, False)])
    fetch(later, tmp_path, window_start=datetime(2024, 6, 1, tzinfo=UTC))
    assert parse_ts(later.calls[0][1]["since"]) == parse_ts(state["complete_until"]) - OVERLAP
    assert read_json(tmp_path / "state.json")["window_start"] == "2024-06-01T00:00:00Z"


def test_cache_without_a_stored_window_is_refetched_from_the_window_once(tmp_path):
    # a state.json written before the window was stored: it is not known what window it covers
    write_json(tmp_path / "20240101T000000_0000.json", [{"id": 1}])
    write_json(
        tmp_path / "state.json",
        {"complete_until": "2024-06-01T00:00:00Z", "completed_runs": ["20240101T000000"]},
    )

    client = FakeClient([page([{"id": 2}], None, False)])
    fetch(client, tmp_path)
    assert client.calls[0][1]["since"] == "2024-01-01T00:00:00Z"

    again = FakeClient([page([{"id": 3}], None, False)])
    fetch(again, tmp_path)
    assert parse_ts(again.calls[0][1]["since"]) > WINDOW  # recorded: incremental from here on


def test_full_ignores_complete_until(tmp_path):
    fetch(FakeClient([page([{"id": 1}], None, False)]), tmp_path)

    client = FakeClient([page([{"id": 2}], None, False)])
    fetch(client, tmp_path, full=True)

    assert client.calls[0][1]["since"] == "2024-01-01T00:00:00Z"
    state = read_json(tmp_path / "state.json")
    assert len(state["completed_runs"]) == 2 and state["run"] is None


def test_window_widened_during_an_unfinished_run_is_refetched_by_the_next_run(tmp_path):
    fetch(FakeClient([page([{"id": 1}], None, False)]), tmp_path)
    broken = FakeClient([page([{"id": 2}], "c2", True), RuntimeError("stopped")])
    with pytest.raises(RuntimeError):
        fetch(broken, tmp_path)  # a run under the 2024 window is left half done

    earlier = datetime(2023, 6, 1, tzinfo=UTC)
    resumed = FakeClient([page([{"id": 3}], None, False)])
    fetch(resumed, tmp_path, window_start=earlier)  # finishes that run as it was started
    assert parse_ts(resumed.calls[0][1]["since"]) > earlier

    fresh = FakeClient([page([{"id": 0}], None, False)])
    fetch(fresh, tmp_path, window_start=earlier)
    assert fresh.calls[0][1]["since"] == "2023-06-01T00:00:00Z"


def test_crash_between_page_write_and_state_write_resumes_without_a_gap(tmp_path, monkeypatch):
    import brain.adapters.runs as runs

    real_write = runs.write_json
    pages_written: list[Path] = []

    def crash_on_second_checkpoint(path: Path, data) -> None:
        if path.name == "state.json" and len(pages_written) == 2:
            raise RuntimeError("disk full")
        real_write(path, data)
        if path.name != "state.json":
            pages_written.append(path)

    monkeypatch.setattr(runs, "write_json", crash_on_second_checkpoint)
    first = FakeClient([page([{"id": 1}], "c1", True), page([{"id": 2}], "c2", False)])
    with pytest.raises(RuntimeError, match="disk full"):
        fetch(first, tmp_path)
    monkeypatch.setattr(runs, "write_json", real_write)
    assert [c[1]["after"] for c in first.calls] == [None, "c1"]
    assert len(pages_written) == 2  # page 1 is on disk but the checkpoint still says page 0 is done

    second = FakeClient([page([{"id": 2}], "c2", False)])
    fetch(second, tmp_path)

    assert [c[1]["after"] for c in second.calls] == ["c1"]  # page 1 fetched again, not page 2
    state = read_json(tmp_path / "state.json")
    assert len(state["completed_runs"]) == 1 and state["run"] is None
    nodes = [n["id"] for p in completed_pages(tmp_path) for n in read_json(p)]
    assert nodes == [1, 2]  # the orphan page was overwritten in place: nothing doubled or lost
