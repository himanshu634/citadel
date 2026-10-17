"""The `backend` command line.

Why: the operator actions that touch what the server keeps (build history, the company slug
registry) live with the server, apart from the `brain` CLI that builds and queries the graph.
Commands stay thin, like the `brain` ones, and share its argument checks.
"""

from __future__ import annotations

import typer
from agents import checkpoint
from agents.graphs import agent_graph_name, keeper_graph_name
from agents.keeper.store import delete_keeper_graph
from agents.traces import TraceStore
from brain import db
from brain.cli_util import connected, graph_name

from backend.jobs import JobRunner

app = typer.Typer(help="Company Brain backend: the HTTP API and the commands around it.")


@app.callback()
def main() -> None:
    """Keeps `reset` a named command, so more can be added without changing how it is called."""


@app.command()
def reset(slug: str, yes: bool = typer.Option(False, "--yes", help="Confirm deletion.")) -> None:
    """Delete everything the slug left in the graph store and its history: graphs brain_<slug>,
    agent_<slug> and keeper_<slug> (the Keeper's ledger), data/jobs/<slug>.json and
    data/traces/<slug>.jsonl (the Ask traces).
    companies/<slug>.yaml and the raw cache in data/raw/ are kept (a refetch is slow). Frees the
    slug for a new company."""
    name = graph_name(slug)
    agent = agent_graph_name(slug)
    keeper = keeper_graph_name(slug)
    if not yes:
        typer.secho(
            f"This deletes graphs {name}, {agent} and {keeper} and the build and Ask history of "
            f"{slug}. "
            "Re-run with --yes (make reset: CONFIRM=1).",
            fg="yellow",
        )
        raise typer.Exit(1)
    connected()
    deleted = []
    if db.delete_graph(slug):
        deleted.append(name)
    if checkpoint.delete_agent_graph(slug):
        deleted.append(agent)
    if delete_keeper_graph(slug):
        deleted.append(keeper)
    if JobRunner().forget(slug):
        deleted.append(f"data/jobs/{slug}.json")
    if TraceStore(slug).forget():
        deleted.append(f"data/traces/{slug}.jsonl")
    typer.echo(f"Deleted {', '.join(deleted)}." if deleted else f"Nothing to delete for {slug}.")


if __name__ == "__main__":
    app()
