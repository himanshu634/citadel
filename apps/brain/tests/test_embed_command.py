"""`brain embed` and ingest share one embed step: the chunk backfill, then the embed stage."""

from __future__ import annotations

from brain import cli, embeddings, loader, pipeline
from typer.testing import CliRunner


def record_calls(monkeypatch) -> list[tuple]:
    calls: list[tuple] = []
    monkeypatch.setattr(loader, "backfill_chunks", lambda slug: calls.append(("backfill", slug)))

    def embed_pending(slug, everything=False, on_event=None):
        calls.append(("embed", slug, everything))
        return embeddings.EmbedReport(embedded=2)

    monkeypatch.setattr(embeddings, "embed_pending", embed_pending)
    return calls


def test_embed_command_backfills_chunks_before_embedding(monkeypatch):
    calls = record_calls(monkeypatch)
    monkeypatch.setattr(cli, "company", lambda slug: None)
    monkeypatch.setattr(cli, "connected", lambda: None)
    out = CliRunner().invoke(cli.app, ["embed", "acme", "--all"])
    assert out.exit_code == 0, out.output
    assert calls == [("backfill", "acme"), ("embed", "acme", True)]
    assert "embedded 2 chunks" in out.output


def test_pipeline_embed_is_the_step_ingest_ends_with(monkeypatch):
    calls = record_calls(monkeypatch)
    report = pipeline.embed("acme")
    assert calls == [("backfill", "acme"), ("embed", "acme", False)]
    assert report.embedded == 2
