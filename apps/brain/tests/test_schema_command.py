"""`brain schema`: a vector index of another size is an error, not a warning."""

from __future__ import annotations

from types import SimpleNamespace

from brain import cli, schema
from typer.testing import CliRunner

MISMATCH = "Chunk.embedding vector index has dimension 4, but EMBEDDING_DIM=768. Drop the index."


def test_schema_command_fails_on_a_mismatched_vector_index(monkeypatch):
    monkeypatch.setattr(cli, "company", lambda slug: SimpleNamespace(graph_name="brain_acme"))
    monkeypatch.setattr(cli, "connected", lambda: None)

    def apply_schema(slug, on_event=None):
        raise schema.SchemaMismatch(MISMATCH)

    monkeypatch.setattr(schema, "apply_schema", apply_schema)
    out = CliRunner().invoke(cli.app, ["schema", "acme"])
    assert out.exit_code == 1
    assert MISMATCH in out.output
