"""Apply the graph schema (indexes) to one company graph.

Why: indexes make MERGE-on-uid and the named tools fast, and the full-text and vector
indexes enable search. Setup must be safe to re-run, so "already indexed" errors are skipped.
The statements live in queries/schema/*.cypher; this module only runs them in order.

A vector index of another size than EMBEDDING_DIM is an error (`SchemaMismatch`, after a
failed `prepare` event), not a warning: FalkorDB accepts a vector of the wrong size and never
indexes it, so the build would look fine while semantic search finds nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from redis.exceptions import ResponseError

from brain import db, queries
from brain.config import get_settings
from brain.events import BuildEvent, OnEvent, noop

SCHEMA_FILES = ["schema/range_indexes", "schema/fulltext_indexes", "schema/vector_index"]


@dataclass
class SchemaReport:
    created: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)


class SchemaMismatch(RuntimeError):
    """An index the graph already holds does not fit the settings; the message says what to do."""


def apply_schema(slug: str, on_event: OnEvent | None = None) -> SchemaReport:
    """Run the schema files on brain_<slug>. Raises SchemaMismatch (after emitting a failed
    `prepare` event) when the Chunk vector index has another dimension than EMBEDDING_DIM."""
    emit = on_event or noop
    emit(BuildEvent(slug, "prepare", "running"))
    dim = get_settings().embedding_dim
    report = SchemaReport()
    for name in SCHEMA_FILES:
        for stmt in queries.get(name).statements():
            # The only substitution: an int from settings, into a placeholder FalkorDB cannot
            # take as a parameter (index OPTIONS). See queries/schema/vector_index.cypher.
            stmt = stmt.replace("{{EMBEDDING_DIM}}", str(int(dim)))
            try:
                db.run_text(slug, stmt)
                report.created.append(stmt)
            except ResponseError as e:
                if "already indexed" not in str(e):
                    raise
                report.existing.append(stmt)
    mismatch = _check_vector_dim(slug, dim)
    if mismatch is not None:
        emit(BuildEvent(slug, "prepare", "failed", message=mismatch))
        raise SchemaMismatch(mismatch)
    emit(BuildEvent(slug, "prepare", "done"))
    return report


def list_indexes(slug: str) -> list[dict]:
    return db.run(slug, "schema/list_indexes", read_only=True)


def _check_vector_dim(slug: str, dim: int) -> str | None:
    """What is wrong with the Chunk vector index's dimension, or None when it fits."""
    for idx in list_indexes(slug):
        if idx["label"] != "Chunk":
            continue
        actual = (idx["options"].get("embedding") or {}).get("dimension")
        if actual is not None and actual != dim:
            return (
                f"Chunk.embedding vector index has dimension {actual}, but EMBEDDING_DIM={dim}. "
                "Drop the index (or `make reset`) and re-run `brain schema`."
            )
    return None
