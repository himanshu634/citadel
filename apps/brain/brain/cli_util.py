"""Checks and formatting the command lines of every package share.

Why: `brain`, `agents` and `backend` each have a CLI, and each takes a company slug, loads
companies/<slug>.yaml, needs FalkorDB and prints rows the same way. One copy here keeps their
messages identical, and the other packages import public names instead of reaching into
`brain.cli`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import NoReturn

import typer
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

from brain import config, db

LABEL_KEYS = ("name", "login", "system", "number", "title", "type", "uid")  # first found wins


def connected() -> None:
    """Exit with a hint unless FalkorDB answers."""
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


def fail(msg: str) -> NoReturn:
    typer.secho(msg, fg="red", err=True)
    raise typer.Exit(1)


def graph_name(slug: str) -> str:
    """brain_<slug>, or exit with a message when the slug is not a valid one."""
    try:
        return config.graph_name(slug)
    except ValueError as e:
        fail(f"{e}. Use lowercase letters, digits and underscores, e.g. 'acme'.")


def company(slug: str) -> config.CompanyConfig:
    """The company's config, or exit with a message when the slug or the file is bad."""
    graph_name(slug)
    try:
        return config.load_company(slug)
    except (FileNotFoundError, ValueError) as e:  # ValidationError is a ValueError
        detail = str(e) if not isinstance(e, ValidationError) else f"invalid config:\n{e}"
        fail(f"companies/{slug}.yaml: {detail}")


def short(key: str, value, width: int) -> str:
    """One readable cell: epoch seconds as dates, lists of maps by their first field."""
    if key.endswith("_ts") and isinstance(value, int):
        return datetime.fromtimestamp(value, UTC).strftime("%Y-%m-%d")
    if key.endswith("_at") and isinstance(value, str):
        return value[:10]
    if isinstance(value, list):
        text = ", ".join(label(v) for v in value)
    elif isinstance(value, float):
        text = f"{value:.3g}"
    else:
        text = "-" if value is None else str(value)
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def label(item) -> str:
    if not isinstance(item, dict):
        return str(item)
    return str(next((item[k] for k in LABEL_KEYS if item.get(k) is not None), ""))
