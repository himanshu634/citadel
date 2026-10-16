"""The `brain` command line.

Why: one entry point for every operator action (set up a company, build its schema, ingest,
query, reset). Each command takes the company slug and works only on graph brain_<slug>.
Commands stay thin: they parse arguments and call plain functions in the other modules.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib import resources
from typing import Annotated

import typer
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError
from rich.console import Console
from rich.table import Table

from brain import config, db, pipeline, schema, tools
from brain.adapters.github.client import GithubError

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
    try:
        for line in pipeline.fetch(slug, only=source):
            typer.echo(f"fetch {line}")
    except (PermissionError, GithubError) as e:
        _fail(str(e))


@app.command()
def ingest(
    slug: str,
    full: bool = typer.Option(False, "--full", help="Ignore sync cursors; reload everything."),
    source: str = SOURCE_OPT,
) -> None:
    """Transform step: cache/local files -> canonical records -> graph brain_<slug>."""
    cfg = _company(slug)
    _connected()
    try:
        report = pipeline.ingest(slug, full=full, only=source)
    except PermissionError as e:
        _fail(str(e))
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


@app.command()
def ask(
    slug: str,
    question: str,
    thread: str = typer.Option(None, "--thread", help="Continue an earlier conversation."),
) -> None:
    """Ask brain_<slug> a question. Claude answers from the graph, with numbered sources."""
    _company(slug)
    _connected()
    answer = _run_ask(slug, question, thread)
    _print_answer(answer)
    typer.secho(f"follow up with --thread {answer.thread_id}", dim=True)


@app.command()
def chat(
    slug: str,
    thread: str = typer.Option(None, "--thread", help="Continue an earlier conversation."),
    offline: bool = typer.Option(
        False,
        "--offline",
        help="One scripted turn (a list_systems call) instead of Claude: no API key needed. "
        "Checks the router, the graph tools and the checkpointer end to end.",
    ),
) -> None:
    """Talk to brain_<slug> in one thread. An empty line or Ctrl-D ends the chat."""
    _company(slug)
    _connected()
    if offline:
        from brain.agents.offline import OfflineClient

        answer = _run_ask(slug, "Which systems does the graph know?", thread, OfflineClient())
        _print_answer(answer)
        typer.secho(
            f"thread {answer.thread_id} holds {answer.thread_messages} messages in "
            f"{config.agent_graph_name(slug)}; add a turn with --thread {answer.thread_id}",
            dim=True,
        )
        return
    typer.secho("Ask about the graph. An empty line ends the chat.", dim=True)
    while True:
        try:
            question = typer.prompt("you", default="", show_default=False)
        except typer.Abort:
            break
        if not question.strip():
            break
        answer = _run_ask(slug, question, thread)
        thread = answer.thread_id
        _print_answer(answer)
    if thread:
        typer.secho(f"continue later with --thread {thread}", dim=True)


def _run_ask(slug: str, question: str, thread: str | None, client=None):
    import anthropic

    from brain.agents.ask import ask as run_ask

    try:
        return run_ask(
            slug, question, thread_id=thread, client=client, checkpointer=db.checkpointer(slug)
        )
    except anthropic.AuthenticationError:
        _fail("Anthropic rejected the credentials. Check ANTHROPIC_API_KEY in .env.")
    except TypeError as e:  # the SDK raises this when it finds no credentials at all
        if "authentication" not in str(e):
            raise
        _fail("No Anthropic credentials. Set ANTHROPIC_API_KEY in .env, or try --offline.")
    except anthropic.APIConnectionError as e:
        _fail(f"Cannot reach the Anthropic API: {e}")
    except anthropic.APIStatusError as e:
        _fail(f"Anthropic API error {e.status_code}: {e.message}")


def _print_answer(answer) -> None:
    if answer.text is None:
        reason = {
            "refusal": "Claude declined to answer",
            "max_tokens": "hit the output limit",
            "step_limit": "too many tool calls",
        }
        detail = (answer.stop_details or {}).get("explanation") or ""
        typer.secho(
            f"No answer: {reason.get(answer.stop, 'no answer submitted')}. {detail}", fg="yellow"
        )
    else:
        typer.echo(answer.text)
        if answer.sources:
            typer.echo("\nSources:")
            for i, src in enumerate(answer.sources, 1):
                typer.echo(f"  [{i}] {src.title or src.uid}  {src.url or src.uid}")
        if answer.path:
            typer.echo("\nPath: " + " -> ".join(p.title or p.uid for p in answer.path))
    u = answer.usage
    typer.secho(
        f"\n{answer.model} · in {u.get('input_tokens', 0)} (cache read "
        f"{u.get('cache_read_input_tokens', 0)}) · out {u.get('output_tokens', 0)}",
        dim=True,
    )


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
    _company(slug)
    _connected()
    params = {}
    for kv in [*(args or []), *(param or [])]:
        key, sep, value = kv.partition("=")
        if not sep:
            _fail(f"parameter {kv!r} must look like key=value")
        params[key] = value
    try:
        rows = tools.call(slug, tool, **params)
    except (KeyError, ValidationError) as e:
        _fail(str(e))
    data = [r.model_dump(by_alias=True) for r in rows]
    if as_json:
        typer.echo(json.dumps(data, indent=2, default=str))
        return
    _print_rows(tool, data)


HIDDEN_IN_TABLE = ("url", "evidence", "examples", "declared_owners")  # still in --json
LABEL_KEYS = ("name", "login", "system", "number", "title", "type", "uid")  # first found wins


def _short(key: str, value, width: int) -> str:
    """One readable cell: epoch seconds as dates, lists of maps by their first field."""
    if key.endswith("_ts") and isinstance(value, int):
        return datetime.fromtimestamp(value, UTC).strftime("%Y-%m-%d")
    if key.endswith("_at") and isinstance(value, str):
        return value[:10]
    if isinstance(value, list):
        text = ", ".join(_label(v) for v in value)
    elif isinstance(value, float):
        text = f"{value:.3g}"
    else:
        text = "-" if value is None else str(value)
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _label(item) -> str:
    if not isinstance(item, dict):
        return str(item)
    return str(next((item[k] for k in LABEL_KEYS if item.get(k) is not None), ""))


def _print_rows(tool: str, rows: list[dict]) -> None:
    if not rows:
        typer.echo(f"{tool}: no rows")
        return
    console = Console()
    if len(rows) == 1 and len(rows[0]) > 6:  # one wide record: print it vertically
        for key, value in rows[0].items():
            console.print(f"[bold]{key}[/bold]: {_short(key, value, 200)}", soft_wrap=True)
        return
    keys = [k for k in rows[0] if not k.endswith("_uid") and k not in HIDDEN_IN_TABLE]
    if "number" in keys:  # the number identifies the item; the uid is in --json
        keys.remove("uid")
    table = Table(title=f"{tool} ({len(rows)} rows; --json for everything)")
    for key in keys:
        table.add_column(key, overflow="fold")
    for r in rows:
        table.add_row(*(_short(k, r[k], 60) for k in keys))
    console.print(table)


if __name__ == "__main__":
    app()
