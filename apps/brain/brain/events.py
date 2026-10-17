"""Build events: what the pipeline reports while it prepares, fetches and loads a company.

Why: a background build job (and the UI's progress table behind it) needs to see each stage as
it happens, without the pipeline knowing who is listening. The pipeline calls an optional
`on_event` callback; the CLI passes none. A callback may raise `BuildStopped` to stop the
pipeline at the next event; the pipeline never catches it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

Stage = Literal["reset", "prepare", "fetch", "records", "normalize", "load", "embed", "done"]
Status = Literal["waiting", "running", "done", "skipped", "failed", "stopped"]


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class BuildEvent:
    slug: str
    stage: Stage
    status: Status
    source: str | None = None  # adapter key, e.g. 'github:FalkorDB/FalkorDB'; None = whole company
    count: int | None = None
    message: str | None = None
    at: str = field(default_factory=_now)  # ISO 8601, UTC
    totals: dict | None = None  # final event only: LoadReport.written and .dropped
    # Set by the build job, not the pipeline: its step counter when the event happened.
    step: int | None = None


OnEvent = Callable[[BuildEvent], None]


class BuildStopped(Exception):
    """Raised by an `on_event` callback to stop the pipeline."""


def noop(event: BuildEvent) -> None:
    """The callback used when the caller passes none."""
