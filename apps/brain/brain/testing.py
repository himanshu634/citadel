"""Test helpers and FalkorDB fixtures shared by every package's tests (a pytest plugin).

Why: the brain's tests and the agents' tests both load the synthetic company into throwaway
graphs (brain_test_*). The root pyproject loads this module with `-p brain.testing`, so each
session fixture is built once per run whichever folder asks for it. Graph tests need a real
FalkorDB (`make up`) and are skipped without one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from redis.exceptions import ConnectionError as RedisConnectionError

from brain import config, db, loader, schema
from brain.adapters.canonical_jsonl import CanonicalJsonlAdapter, CanonicalJsonlSource
from brain.config import CompanyConfig
from brain.normalize import normalize

SYNTHETIC = Path(__file__).resolve().parents[1] / "examples" / "synthetic_company"


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


def write_company(cfg: CompanyConfig) -> Path:
    """Write cfg as companies/<slug>.yaml under the current repo root (tests point
    `config.REPO_ROOT` at a temp folder first)."""
    path = config.companies_dir() / f"{cfg.slug}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False))
    return path


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
