"""Test doubles for the backend's tests: a fake build and a second company.

Why: the job runner and the API tests need a build that runs without FalkorDB or the network,
and the isolation tests need a company that shares no uid with the synthetic one. They live in
the package (not in a conftest) so test files can import them by name. The FalkorDB fixtures
shared with the other packages are in `brain.testing`.
"""

from __future__ import annotations

import threading
from pathlib import Path

from brain.config import CompanyConfig
from brain.events import BuildEvent
from brain.loader import LoadReport
from brain.pipeline import IngestReport

SECOND = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "second_company"
)  # no uid in common


def second_company(slug: str) -> CompanyConfig:
    """A second small company (tests/fixtures/second_company): other people, teams, systems and
    uids than the synthetic one, for isolation tests."""
    return CompanyConfig.model_validate(
        {
            "slug": slug,
            "name": slug,
            "data_permission": "synthetic",
            "window": {"since": "2026-01-01"},
            "sources": [{"type": "canonical_jsonl", "path": str(SECOND)}],
            "systems": {
                "rules": [
                    {"match": "engine/**", "system": "Engine"},
                    {"match": "gateway/**", "system": "Gateway"},
                ],
                "fallback": "depth_1",
            },
        }
    )


# --- a fake build: the job runner's steps without FalkorDB or the network ---------------------

SRC = "github:acme/widgets"

# The events each fake step emits, in the order the real pipeline emits them.
STEP_EVENTS = {
    "prepare": [("prepare", "running", None), ("prepare", "done", None)],
    "fetch": [("fetch", "running", SRC), ("fetch", "done", SRC)],
    "ingest": [
        ("records", "running", SRC),
        ("records", "done", SRC),
        ("normalize", "done", SRC),
        ("load", "running", SRC),
        ("load", "done", SRC),
    ],
}


class FakeSteps:
    """Records calls and emits the real pipeline's events, per source in `sources` (default one,
    SRC). Fetch covers the sources in its `keys` (all for None), like pipeline.fetch; a source
    in `skip_records` stops at a skipped records stage, like an unavailable source. `gate` (when
    given) blocks `prepare` after `gate_at` of its events until the test sets it. `fail_on` makes
    that step raise after `fail_after` of its events (default: before its last one)."""

    def __init__(
        self,
        gate: threading.Event | None = None,
        gate_at: int = 1,
        fail_on: str | None = None,
        fail_after: int | None = None,
        sources: list[str] | None = None,
        skip_records: set[str] | None = None,
    ):
        self.gate = gate
        self.gate_at = gate_at
        self.fail_on = fail_on
        self.fail_after = fail_after
        self.source_keys = sources if sources is not None else [SRC]
        self.skip_records = skip_records or set()
        self.calls: list[str] = []

    def _fetched(self, keys: set[str] | None) -> list[str]:
        return [k for k in self.source_keys if keys is None or k in keys]

    def _events(self, name: str, keys: set[str] | None = None) -> list[tuple]:
        if name == "prepare":
            return STEP_EVENTS["prepare"]
        if name == "fetch":
            return [
                (stage, status, key)
                for key in self._fetched(keys)
                for stage, status, _ in STEP_EVENTS["fetch"]
            ]
        events = []
        for key in self.source_keys:
            if key in self.skip_records:
                events += [("records", "running", key), ("records", "skipped", key)]
            else:
                events += [(stage, status, key) for stage, status, _ in STEP_EVENTS["ingest"]]
        return events

    def _step(self, name, slug, on_event, keys=None):
        events = self._events(name, keys)
        fail_at = len(events) - 1 if self.fail_after is None else self.fail_after
        for i, (stage, status, source) in enumerate(events):
            if name == self.fail_on and i == fail_at:
                raise RuntimeError("boom")
            if name == "prepare" and self.gate is not None and i == self.gate_at:
                assert self.gate.wait(5), "test never opened the gate"
            on_event(BuildEvent(slug, stage, status, source))
        if name == "prepare" and self.gate is not None and self.gate_at == len(events):
            assert self.gate.wait(5), "test never opened the gate"

    def sources(self, slug, keys):
        return self._fetched(keys), list(self.source_keys)

    def reset(self, slug):
        self.calls.append("reset")
        if self.fail_on == "reset":
            raise RuntimeError("boom")

    def prepare(self, slug, on_event):
        self.calls.append("prepare")
        self._step("prepare", slug, on_event)

    def fetch(self, slug, keys, on_event):
        self.calls.append(f"fetch({sorted(keys) if keys is not None else None})")
        self._step("fetch", slug, on_event, keys)

    def ingest(self, slug, full, on_event):
        self.calls.append(f"ingest(full={full})")
        self._step("ingest", slug, on_event)
        report = IngestReport()
        report.load = LoadReport()
        report.load.written["load/person"] = 3
        return report
