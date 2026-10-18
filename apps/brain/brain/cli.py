"""The `brain` command line.

Why: one entry point for every operator action (set up a company, build its schema, ingest,
query). Each command takes the company slug and works only on graph brain_<slug>.
Commands stay thin: they parse arguments and call plain functions in the other modules.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from brain import config, db, embeddings, pipeline, schema, tools
from brain.adapters.github.client import GithubError
from brain.adapters.linear import seed as linear_seed
from brain.adapters.linear.client import LinearClient, LinearError
from brain.adapters.linear.source import LinearSource
from brain.cli_util import company, connected, fail, graph_name, short

app = typer.Typer(help="Company Brain: a company's engineering activity as one FalkorDB graph.")


@app.command()
def init(slug: str, name: str = typer.Option(None, help="Display name (default: slug).")) -> None:
    """Write a commented template config at companies/<slug>.yaml."""
    graph_name(slug)
    path = config.company_path(slug)
    if path.exists():
        typer.secho(f"{path} already exists; not overwriting.", fg="yellow")
        raise typer.Exit(1)
    template = resources.files("brain").joinpath("templates/company.yaml").read_text()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template.format(slug=slug, name=name or slug))
    typer.echo(f"Wrote {path}. Edit sources and systems.rules, then run `make schema SLUG={slug}`.")


@app.command("schema")
def schema_cmd(slug: str) -> None:
    """Create the range, full-text and vector indexes on brain_<slug> (idempotent)."""
    cfg = company(slug)
    connected()
    report = schema.apply_schema(slug)
    typer.echo(
        f"{cfg.graph_name}: {len(report.created)} index statements applied, "
        f"{len(report.existing)} already present."
    )
    if report.backfilled:
        typer.echo(f"  {report.backfilled} nodes given the Node label (loaded before it existed).")
    for idx in schema.list_indexes(slug):
        kinds = ", ".join(f"{p}:{'/'.join(t)}" for p, t in idx["types"].items())
        typer.echo(f"  {idx['label']:<10} {kinds}  [{idx['status']}]")
    for w in report.warnings:
        typer.secho(f"warning: {w}", fg="yellow")


SEED_TICKETS = "apps/brain/examples/synthetic_company/tickets"


@app.command("linear-seed")
def linear_seed_cmd(
    slug: str,
    tickets: Annotated[
        Path | None, typer.Option("--tickets", help=f"Tickets folder (default: {SEED_TICKETS}).")
    ] = None,
    yes: bool = typer.Option(False, "--yes", help="Write to Linear (without it: print the plan)."),
) -> None:
    """Copy the synthetic tickets into the Linear workspace named in companies/<slug>.yaml.
    Without --yes it only prints the plan. Writes to Linear, so it needs data_permission:
    synthetic and LINEAR_API_KEY. Safe to re-run: already-created tickets are skipped."""
    cfg = company(slug)
    sources = [s for s in cfg.sources if isinstance(s, LinearSource)]
    if len(sources) != 1:
        fail(f"companies/{slug}.yaml needs exactly one `linear` source (found {len(sources)}).")
    source = sources[0]
    folder = cfg.resolve(tickets or Path(SEED_TICKETS))
    try:
        data = linear_seed.load_seed(folder)
    except (OSError, ValueError) as e:
        fail(f"cannot read tickets in {folder}: {e}")
    typer.echo(
        f"Linear workspace {source.workspace!r} (company {slug}): {len(data.tickets)} tickets "
        f"in teams {', '.join(data.teams)}, {len(data.blocks)} blocks, "
        f"{len(data.attachments)} attachments."
    )
    if not yes:
        typer.secho(
            "Nothing written. Re-run with --yes (make linear-seed: CONFIRM=1).", fg="yellow"
        )
        return
    state = config.raw_dir(slug, "linear") / source.workspace / "seed_state.json"
    try:
        with LinearClient(log=typer.echo) as client:
            report = linear_seed.seed(client, cfg, source, data, state, log=typer.echo)
    except (PermissionError, LinearError, RuntimeError) as e:
        fail(str(e))
    typer.echo(f"Created {report.created}, skipped {report.skipped} already present.")


SOURCE_OPT = typer.Option(None, "--source", help="Only this source type, e.g. github.")
FETCH_FULL_OPT = typer.Option(
    False, "--full", help="Pull the whole window again, not only what changed since last time."
)


@app.command()
def fetch(slug: str, full: bool = FETCH_FULL_OPT, source: str = SOURCE_OPT) -> None:
    """Network step: pull raw data for each source into data/raw/<slug>/ (cached, resumable)."""
    company(slug)
    try:
        for line in pipeline.fetch(slug, only=source, full=full):
            typer.echo(f"fetch {line}")
    except (PermissionError, GithubError) as e:
        fail(str(e))


@app.command()
def ingest(
    slug: str,
    full: bool = typer.Option(False, "--full", help="Ignore sync cursors; reload everything."),
    source: str = SOURCE_OPT,
) -> None:
    """Transform step: cache/local files -> canonical records -> graph brain_<slug>."""
    cfg = company(slug)
    connected()
    try:
        report = pipeline.ingest(slug, full=full, only=source)
    except PermissionError as e:
        fail(str(e))
    for s in report.sources:
        if s.skipped_reason:
            typer.secho(f"skipped {s.key}: {s.skipped_reason}", fg="yellow")
        else:
            typer.echo(f"ingested {s.key}: {s.read} read, {s.loaded} loaded")
            if s.incomplete:
                typer.secho(
                    f"  {s.incomplete}; sync cursor kept until a fetch completes it", fg="yellow"
                )
    dropped = {q: n for q, n in report.load.dropped.items() if n}
    for q, n in sorted(dropped.items()):
        typer.secho(f"  dropped {n} rows in {q} (an end node is not in the graph)", fg="yellow")
    _print_embed(report.embed)
    _print_stats(slug, f"{cfg.graph_name} now holds:")


@app.command()
def embed(
    slug: str,
    everything: bool = typer.Option(
        False, "--all", help="Embed every chunk again, not only new or changed text."
    ),
) -> None:
    """Embed the chunks of brain_<slug> whose text or model changed (ingest runs this too)."""
    company(slug)
    connected()
    _print_embed(pipeline.embed(slug, everything=everything))


def _print_embed(report: embeddings.EmbedReport) -> None:
    if report.skipped_reason:
        done = f" after {report.embedded} chunks" if report.embedded else ""
        typer.secho(f"embedding skipped{done}: {report.skipped_reason}", fg="yellow")
    else:
        typer.echo(f"embedded {report.embedded} chunks")


@app.command()
def sync(
    slug: str,
    full: bool = typer.Option(
        False, "--full", help="Pull the whole window again and reload everything."
    ),
    source: str = SOURCE_OPT,
) -> None:
    """fetch + ingest."""
    fetch(slug, full=full, source=source)
    ingest(slug, full=full, source=source)


@app.command()
def stats(slug: str) -> None:
    """Node counts per label and relationship counts per type."""
    company(slug)
    connected()
    _print_stats(slug, f"{config.graph_name(slug)}:")


def _print_stats(slug: str, title: str) -> None:
    rows = db.run(slug, "tools/graph_stats", read_only=True)
    typer.echo(title)
    for kind in ("node", "relationship"):
        part = sorted((r for r in rows if r["kind"] == kind), key=lambda r: -r["count"])
        typer.echo(f"  {kind}s: " + (", ".join(f"{r['type']}={r['count']}" for r in part) or "-"))


@app.command("tools")
def tools_cmd() -> None:
    """List the named query tools and their parameters."""
    for t in tools.TOOLS.values():
        fields = t.params.model_fields
        params = ", ".join(
            name if f.is_required() else f"{name}={f.default}" for name, f in fields.items()
        )
        typer.secho(f"{t.name}({params})", bold=True)
        typer.echo(f"    {t.description}")


@app.command()
def query(
    slug: str,
    tool: str,
    args: Annotated[list[str] | None, typer.Argument(help="Parameters as key=value.")] = None,
    param: Annotated[
        list[str] | None, typer.Option("--param", "-p", help="key=value (repeatable).")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print rows as JSON.")] = False,
) -> None:
    """Run a named query tool and print its rows: `brain query falkordb impact_of system=CI`."""
    company(slug)
    connected()
    params = {}
    for kv in [*(args or []), *(param or [])]:
        key, sep, value = kv.partition("=")
        if not sep:
            fail(f"parameter {kv!r} must look like key=value")
        params[key] = value
    try:
        rows = tools.call(slug, tool, **params)
    except (KeyError, ValidationError) as e:
        fail(str(e))
    data = [r.model_dump(by_alias=True) for r in rows]
    if as_json:
        typer.echo(json.dumps(data, indent=2, default=str))
        return
    _print_rows(tool, data)


HIDDEN_IN_TABLE = ("url", "evidence", "examples", "declared_owners")  # still in --json


def _print_rows(tool: str, rows: list[dict]) -> None:
    if not rows:
        typer.echo(f"{tool}: no rows")
        return
    console = Console()
    if len(rows) == 1 and len(rows[0]) > 6:  # one wide record: print it vertically
        for key, value in rows[0].items():
            console.print(f"[bold]{key}[/bold]: {short(key, value, 200)}", soft_wrap=True)
        return
    keys = [k for k in rows[0] if not k.endswith("_uid") and k not in HIDDEN_IN_TABLE]
    if "number" in keys:  # the number identifies the item; the uid is in --json
        keys.remove("uid")
    table = Table(title=f"{tool} ({len(rows)} rows; --json for everything)")
    for key in keys:
        table.add_column(key, overflow="fold")
    for r in rows:
        table.add_row(*(short(k, r[k], 60) for k in keys))
    console.print(table)


if __name__ == "__main__":
    app()
