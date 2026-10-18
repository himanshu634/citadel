"""The named Cypher files agree with what is written to brain_<slug>: no index on a label
nothing creates, and path_between walks every relationship type the loader writes (bar FROM)."""

from __future__ import annotations

import re
from pathlib import Path

from brain import queries

QUERIES = Path(queries.__file__).resolve().parents[1] / "queries"


def _written(pattern: str, *folders: str) -> set[str]:
    found: set[str] = set()
    for folder in folders:
        for path in (QUERIES / folder).glob("*.cypher"):
            found |= set(re.findall(pattern, path.read_text()))
    return found


def test_range_indexes_cover_only_written_labels():
    """Every indexed label is one the loader or the Keeper's projection creates."""
    labels = re.findall(r"CREATE INDEX FOR \(n:(\w+)\)", queries.get("schema/range_indexes").body)
    written = _written(r"MERGE \(\w+:(\w+)", "load", "keeper")
    assert set(labels) <= written, sorted(set(labels) - written)


def test_path_between_walks_every_loaded_relationship_type():
    """The walk follows exactly the loader's relationship types, less FROM (text chunks). The
    Keeper's Claim edges (ABOUT, EVIDENCE) are notes on entities, not activity between them."""
    body = queries.get("tools/path_between").body
    listed = set(re.findall(r"'([A-Z_]+)'", body.split("relTypes:")[1].split("]")[0]))
    written = _written(r"MERGE \(\w+\)-\[\w*:([A-Z_]+)\]", "load") - {"FROM"}
    assert listed == written, (sorted(listed - written), sorted(written - listed))
