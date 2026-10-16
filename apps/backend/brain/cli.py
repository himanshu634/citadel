"""The `brain` command line.

Why: one entry point for every operator action (set up a company, build its schema, ingest,
query, reset). Each command takes the company slug and works only on graph brain_<slug>.
Commands stay thin: they parse arguments and call plain functions in the other modules.
"""

from __future__ import annotations

from importlib import resources

import typer
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

from brain import config, db, pipeline, schema

app = typer.Typer(help="Company Brain: a company's engineering activity as one FalkorDB graph.")


def _connected() -> None:
    s = config.get_settings()
    try:
        db.ping()
    except RedisConnectionError:
        typer.secho(
            f"Cannot reach FalkorDB at {s.falkordb_host}:{s.falkordb_port}. "
            "Start it with `make up` or check FALKORDB_* in .env.",
            fg="red",
            err=True,
        )
        raise typer.Exit(1) from None


def _fail(msg: str) -> None:
    typer.secho(msg, fg="red", err=True)
    raise typer.Exit(1)


def _graph_name(slug: str) -> str:
    try:
        return config.graph_name(slug)
    except ValueError as e:
        _fail(f"{e}. Use lowercase letters, digits and underscores, e.g. 'acme'.")


def _company(slug: str) -> config.CompanyConfig:
    _graph_name(slug)
    try:
        return config.load_company(slug)
    except (FileNotFoundError, ValueError) as e:  # ValidationError is a ValueError
        detail = str(e) if not isinstance(e, ValidationError) else f"invalid config:\n{e}"
        _fail(f"companies/{slug}.yaml: {detail}")


@app.command()
def init(slug: str, name: str = typer.Option(None, help="Display name (default: slug).")) -> None:
    """Write a commented template config at companies/<slug>.yaml."""
    _graph_name(slug)
    path = config.companies_dir() / f"{slug}.yaml"
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
    cfg = _company(slug)
    _connected()
    report = schema.apply_schema(slug)
    typer.echo(
        f"{cfg.graph_name}: {len(report.created)} index statements applied, "
        f"{len(report.existing)} already present."
    )
    for idx in schema.list_indexes(slug):
        kinds = ", ".join(f"{p}:{'/'.join(t)}" for p, t in idx["types"].items())
        typer.echo(f"  {idx['label']:<10} {kinds}  [{idx['status']}]")
    for w in report.warnings:
        typer.secho(f"warning: {w}", fg="yellow")


@app.command()
def reset(slug: str, yes: bool = typer.Option(False, "--yes", help="Confirm deletion.")) -> None:
    """Delete the whole graph brain_<slug>. Raw caches in data/ are kept."""
    name = _graph_name(slug)
    if not yes:
        typer.secho(
            f"This deletes graph {name}. Re-run with --yes (make reset: CONFIRM=1).", fg="yellow"
        )
        raise typer.Exit(1)
    _connected()
    deleted = db.delete_graph(slug)
    typer.echo(f"Deleted {name}." if deleted else f"{name} does not exist; nothing to delete.")


SOURCE_OPT = typer.Option(None, "--source", help="Only this source type, e.g. github.")


@app.command()
def fetch(slug: str, source: str = SOURCE_OPT) -> None:
    """Network step: pull raw data for each source into data/raw/<slug>/ (cached, resumable)."""
    _company(slug)
    for line in pipeline.fetch(slug, only=source):
        typer.echo(f"fetch {line}")


@app.command()
def ingest(
    slug: str,
    full: bool = typer.Option(False, "--full", help="Ignore sync cursors; reload everything."),
    source: str = SOURCE_OPT,
) -> None:
    """Transform step: cache/local files -> canonical records -> graph brain_<slug>."""
    cfg = _company(slug)
    _connected()
    report = pipeline.ingest(slug, full=full, only=source)
    for s in report.sources:
        if s.skipped_reason:
            typer.secho(f"skipped {s.key}: {s.skipped_reason}", fg="yellow")
        else:
            typer.echo(f"ingested {s.key}: {s.read} read, {s.loaded} loaded")
    dropped = {q: n for q, n in report.load.dropped.items() if n}
    for q, n in sorted(dropped.items()):
        typer.secho(f"  dropped {n} rows in {q} (an end node is not in the graph)", fg="yellow")
    _print_stats(slug, f"{cfg.graph_name} now holds:")


@app.command()
def sync(slug: str, full: bool = typer.Option(False, "--full"), source: str = SOURCE_OPT) -> None:
    """fetch + ingest."""
    fetch(slug, source=source)
    ingest(slug, full=full, source=source)


@app.command()
def stats(slug: str) -> None:
    """Node counts per label and relationship counts per type."""
    _company(slug)
    _connected()
    _print_stats(slug, f"{config.graph_name(slug)}:")


def _print_stats(slug: str, title: str) -> None:
    rows = db.run(slug, "tools/graph_stats", read_only=True)
    typer.echo(title)
    for kind in ("node", "relationship"):
        part = sorted((r for r in rows if r["kind"] == kind), key=lambda r: -r["count"])
        typer.echo(f"  {kind}s: " + (", ".join(f"{r['type']}={r['count']}" for r in part) or "-"))


if __name__ == "__main__":
    app()
