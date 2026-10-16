"""The `brain` CLI against a real FalkorDB: reset frees a slug for a new company."""

from __future__ import annotations

from agents import checkpoint
from brain import cli, config, db
from conftest import needs_graph
from typer.testing import CliRunner

pytestmark = needs_graph

SLUG = "test_reset"


def test_reset_deletes_both_graphs_and_the_build_history_but_keeps_the_raw_cache(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    db.graph(SLUG).query("CREATE (:Probe)")
    db.client().select_graph(checkpoint.agent_graph_name(SLUG)).query("CREATE (:Probe)")
    jobs = tmp_path / "data" / "jobs" / f"{SLUG}.json"
    raw = tmp_path / "data" / "raw" / SLUG / "github" / "page.json"
    for path in (jobs, raw):
        path.parent.mkdir(parents=True)
        path.write_text("{}")
    try:
        refused = CliRunner().invoke(cli.app, ["reset", SLUG])
        assert refused.exit_code == 1 and jobs.exists()
        assert len(checkpoint.company_graphs(SLUG)) == 2

        done = CliRunner().invoke(cli.app, ["reset", SLUG, "--yes"])
        assert done.exit_code == 0, done.output
        assert checkpoint.company_graphs(SLUG) == [] and not jobs.exists()
        assert raw.exists()
        again = CliRunner().invoke(cli.app, ["reset", SLUG, "--yes"])
        assert again.exit_code == 0 and "Nothing to delete" in again.output
    finally:
        db.delete_graph(SLUG)
        checkpoint.delete_agent_graph(SLUG)
