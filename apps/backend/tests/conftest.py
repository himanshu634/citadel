"""Shared fixtures. Graph tests use a real FalkorDB (`make up`) and are skipped without one.

They write only to throwaway graphs named brain_test_*, never to a company's real graph.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from brain import db, loader, schema
from brain.adapters.canonical_jsonl import CanonicalJsonlAdapter, CanonicalJsonlSource
from brain.config import CompanyConfig
from brain.events import BuildEvent
from brain.loader import LoadReport
from brain.normalize import normalize
from brain.pipeline import IngestReport
from redis.exceptions import ConnectionError as RedisConnectionError

SYNTHETIC = Path(__file__).resolve().parents[1] / "examples" / "synthetic_company"
SECOND = Path(__file__).resolve().parent / "fixtures" / "second_company"  # no uid in common


def falkordb_up() -> bool:
    try:
        return db.ping()
    except (RedisConnectionError, OSError):
        return False


needs_graph = pytest.mark.skipif(not falkordb_up(), reason="FalkorDB not reachable (make up)")


def synthetic_company(
    slug: str, folder: Path = SYNTHETIC, with_tickets: bool = False
) -> CompanyConfig:
    """The synthetic company's config (companies/synthetic.yaml) under a test slug; with_tickets
    adds its tickets folder as a second canonical_jsonl source."""
    sources = [{"type": "canonical_jsonl", "path": str(folder)}]
    if with_tickets:
        sources.append({"type": "canonical_jsonl", "path": str(folder / "tickets")})
    return CompanyConfig.model_validate(
        {
            "slug": slug,
            "name": slug,
            "data_permission": "synthetic",
            "window": {"since": "2026-01-01"},
            "sources": sources,
            "systems": {
                "rules": [
                    {"match": "services/auth/**", "system": "Auth"},
                    {"match": "services/billing/**", "system": "Billing"},
                    {"match": "web/**", "system": "Web app"},
                    {"match": "infra/**", "system": "Infra"},
                ],
                "fallback": "depth_1",
                "ignore": ["**/*.lock"],
            },
            "people": {"bots": ["ci-bot"]},
        }
    )


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


def load_company(cfg: CompanyConfig) -> None:
    """schema + canonical_jsonl (every source) -> normalize -> loader, without the CLI or
    companies/ files."""
    schema.apply_schema(cfg.slug)
    records = []
    for source in cfg.sources:
        assert isinstance(source, CanonicalJsonlSource)
        records += CanonicalJsonlAdapter().records(cfg, source, Path("/nonexistent"))
    loader.load(cfg.slug, normalize(records, cfg))


@pytest.fixture(scope="session")
def synthetic_graph():
    """brain_test_synthetic loaded once per test run; deleted afterwards."""
    if not falkordb_up():
        pytest.skip("FalkorDB not reachable (make up)")
    slug = "test_synthetic"
    db.delete_graph(slug)
    load_company(synthetic_company(slug))
    yield slug
    db.delete_graph(slug)


@pytest.fixture(scope="session")
def ticket_graph():
    """brain_test_tickets_synth: the synthetic company plus its ten tickets; deleted afterwards."""
    if not falkordb_up():
        pytest.skip("FalkorDB not reachable (make up)")
    slug = "test_tickets_synth"
    db.delete_graph(slug)
    load_company(synthetic_company(slug, with_tickets=True))
    yield slug
    db.delete_graph(slug)


@pytest.fixture(scope="session")
def second_graph():
    """brain_test_second loaded once per test run; deleted afterwards."""
    if not falkordb_up():
        pytest.skip("FalkorDB not reachable (make up)")
    slug = "test_second"
    db.delete_graph(slug)
    load_company(second_company(slug))
    yield slug
    db.delete_graph(slug)


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
