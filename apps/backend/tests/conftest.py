"""Shared fixtures. Graph tests use a real FalkorDB (`make up`) and are skipped without one.

They write only to throwaway graphs named brain_test_*, never to a company's real graph.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from brain import db, loader, schema
from brain.adapters.canonical_jsonl import CanonicalJsonlAdapter, CanonicalJsonlSource
from brain.config import CompanyConfig
from brain.normalize import normalize
from redis.exceptions import ConnectionError as RedisConnectionError

SYNTHETIC = Path(__file__).resolve().parents[1] / "examples" / "synthetic_company"


def falkordb_up() -> bool:
    try:
        return db.ping()
    except (RedisConnectionError, OSError):
        return False


needs_graph = pytest.mark.skipif(not falkordb_up(), reason="FalkorDB not reachable (make up)")


def synthetic_company(slug: str, folder: Path = SYNTHETIC) -> CompanyConfig:
    """The synthetic company's config (companies/synthetic.yaml) under a test slug."""
    return CompanyConfig.model_validate(
        {
            "slug": slug,
            "name": slug,
            "data_permission": "synthetic",
            "window": {"since": "2026-01-01"},
            "sources": [{"type": "canonical_jsonl", "path": str(folder)}],
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


def load_company(cfg: CompanyConfig) -> None:
    """schema + canonical_jsonl -> normalize -> loader, without the CLI or companies/ files."""
    schema.apply_schema(cfg.slug)
    source = cfg.sources[0]
    assert isinstance(source, CanonicalJsonlSource)
    records = list(CanonicalJsonlAdapter().records(cfg, source, Path("/nonexistent")))
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
