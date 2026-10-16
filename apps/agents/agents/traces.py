"""Online traces: one record per question asked of a company's brain, for watching live use.

Why: a real company graph has no gold answers, so the offline evals (agents/evals) cannot
grade live use. Instead each turn asked from the CLI or the Ask page is kept as one `Trace` with
what needs no reference answer: the tools called, failed tool calls, rejected submit_answer
calls, nudges, how the turn stopped, tokens, latency and how many sources it cited. `summarize`
turns a window of traces into rates and percentiles (GET .../traces/summary). A thumbs up or
down from the Ask page is stored on its trace, and `python -m agents.evals.drafts` turns thumbs-down
turns into draft cases for evals/cases/<slug>.yaml.

Traces live in data/traces/<slug>.jsonl (beside data/jobs/ and data/evals/), append-only: a
`turn` line per question and a `feedback` line per thumbs click; reading folds the latest
feedback onto its turn. Only the CLI and the Ask API record: `ask`, `ask_traced` and the evals
never do, so test and eval runs stay out of the live numbers. `backend reset` deletes the file.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from brain import config
from pydantic import BaseModel, Field, ValidationError

from agents.loop import SUBMIT

if TYPE_CHECKING:
    from agents.ask import Answer

log = logging.getLogger(__name__)

Rating = Literal["up", "down"]
Via = Literal["cli", "api"]
_LOCK = threading.Lock()  # appends from parallel Ask runs never interleave


class Usage(BaseModel):
    """Tokens of one turn, summed over its Claude calls. `total` is all four."""

    input: int = 0  # uncached input
    cache_read: int = 0
    cache_write: int = 0
    output: int = 0
    total: int = 0


class Feedback(BaseModel):
    rating: Rating | None  # None: a thumb taken back
    note: str | None = None
    at: datetime


class Trace(BaseModel):
    id: str
    at: datetime  # when the turn ended (UTC)
    slug: str
    via: Via
    thread_id: str
    question: str
    tools: list[str] = []  # graph tools in call order, repeats kept
    tool_errors: list[str] = []  # "tool: error" per failed call
    rejected: list[str] = []  # why each rejected submit_answer was refused
    nudges: int = 0  # plain-text replies asked to call submit_answer
    stop: str | None = None  # Answer.stop, or "error" when the run raised
    error: str | None = None
    model: str | None = None
    effort: str | None = None
    usage: Usage = Field(default_factory=Usage)
    ms: int = 0  # wall time of the turn
    sources: int = 0  # cited sources
    text: str | None = None  # the answer (None: no answer)
    cited: list[str] = []  # source uids, in marker order
    path: list[str] = []
    feedback: Feedback | None = None  # folded in when read; never written on the turn line

    @property
    def answered(self) -> bool:
        return self.text is not None


# --- building a trace -------------------------------------------------------------------------


def step_summary(steps: list[dict[str, Any]], submit: str = SUBMIT) -> dict[str, Any]:
    """From a turn's `step_done` events: graph tools in order, failed tool calls and rejected
    submit_answer calls (an uncited or made-up uid, a bad marker)."""
    tools = [s for s in steps if s.get("tool") != submit]
    rejected = [s.get("error") for s in steps if s.get("tool") == submit and s.get("error")]
    return {
        "tools": [s["tool"] for s in tools],
        "tool_errors": [f"{s['tool']}: {s['error']}" for s in tools if s.get("error")],
        "rejected": rejected,
        "tool_ms": sum(s.get("ms") or 0 for s in tools),
    }


def usage_of(usage: dict[str, int]) -> Usage:
    """Anthropic usage keys -> Usage."""
    u = Usage(
        input=usage.get("input_tokens", 0),
        cache_read=usage.get("cache_read_input_tokens", 0),
        cache_write=usage.get("cache_creation_input_tokens", 0),
        output=usage.get("output_tokens", 0),
    )
    u.total = u.input + u.cache_read + u.cache_write + u.output
    return u


def new_trace(
    slug: str,
    question: str,
    thread_id: str,
    *,
    via: Via,
    steps: list[dict[str, Any]],
    ms: int,
    answer: Answer | None = None,
    error: str | None = None,
    model: str | None = None,
) -> Trace:
    """The trace of one turn: from its Answer, or (answer None) from a run that raised.
    `model` is the one the turn asked for (None: ANTHROPIC_MODEL); the model that served the
    Answer wins when there is one."""
    summary = step_summary(steps)
    s = config.get_settings()
    base = {
        "id": uuid.uuid4().hex[:12],
        "at": datetime.now(UTC),
        "slug": slug,
        "via": via,
        "thread_id": thread_id,
        "question": question,
        "tools": summary["tools"],
        "tool_errors": summary["tool_errors"],
        "rejected": summary["rejected"],
        "effort": s.anthropic_effort,
        "ms": ms,
    }
    if answer is None:
        return Trace(**base, stop="error", error=error, model=model or s.anthropic_model)
    return Trace(
        **base,
        nudges=answer.nudges,
        stop=answer.stop,
        model=answer.model or model or s.anthropic_model,
        usage=usage_of(answer.usage),
        sources=len(answer.sources),
        text=answer.text,
        cited=[x.uid for x in answer.sources],
        path=[x.uid for x in answer.path],
    )


# --- the store --------------------------------------------------------------------------------


class TraceStore:
    """data/traces/<slug>.jsonl. Writes never raise: a lost trace must not lose the answer."""

    def __init__(self, slug: str, root: Path | None = None):
        self.slug = slug
        self._root = root

    @property
    def path(self) -> Path:
        return (self._root or config.REPO_ROOT / "data" / "traces") / f"{self.slug}.jsonl"

    def add(self, trace: Trace) -> bool:
        line = trace.model_dump(mode="json", exclude={"feedback"})
        return self._append({"kind": "turn", **line})

    def rate(self, trace_id: str, rating: Rating | None, note: str | None = None) -> Trace | None:
        """Store a thumbs on one of this slug's traces; None when there is no such trace."""
        trace = next((t for t in self.read() if t.id == trace_id), None)
        if trace is None:
            return None
        fb = Feedback(rating=rating, note=(note or "").strip() or None, at=datetime.now(UTC))
        if not self._append(
            {"kind": "feedback", "trace_id": trace_id, **fb.model_dump(mode="json")}
        ):
            raise OSError(f"could not write {self.path}")
        return trace.model_copy(update={"feedback": fb})

    def read(self, since: datetime | None = None) -> list[Trace]:
        """Traces in write order, each with its latest feedback; `since` keeps the later ones.
        A line that does not parse (a write cut off by a crash) is skipped."""
        if not self.path.exists():
            return []
        turns: dict[str, Trace] = {}
        feedback: dict[str, Feedback] = {}
        for n, raw in enumerate(self.path.read_text().splitlines(), 1):
            if not raw.strip():
                continue
            try:
                line = json.loads(raw)
                kind = line.pop("kind", None)
                if kind == "turn":
                    trace = Trace.model_validate(line)
                    turns[trace.id] = trace
                elif kind == "feedback":
                    feedback[line.pop("trace_id")] = Feedback.model_validate(line)
            except (ValueError, KeyError, ValidationError):
                log.warning("%s:%d is not a trace line; skipped", self.path, n)
        out = []
        for t in turns.values():
            if since is not None and t.at < since:
                continue
            out.append(t.model_copy(update={"feedback": feedback.get(t.id)}))
        return out

    def forget(self) -> bool:
        if not self.path.exists():
            return False
        self.path.unlink()
        return True

    def _append(self, line: dict[str, Any]) -> bool:
        text = json.dumps(line, default=str) + "\n"
        try:
            with _LOCK:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a") as fh:
                    fh.write(text)
            return True
        except OSError:
            log.exception("could not write a trace to %s", self.path)
            return False


# --- aggregates -------------------------------------------------------------------------------


class Rates(BaseModel):
    """Shares of the window's turns (None when it has none). Every rate counts all turns except
    `zero_source`, which counts answered turns only. `stopped` (the user pressed Stop) and
    `error` (the run raised) are kept apart so they don't read as the agent's own failures."""

    no_answer: float | None = None  # ended without an accepted submit_answer
    step_limit: float | None = None
    refusal: float | None = None
    max_tokens: float | None = None
    stopped: float | None = None
    error: float | None = None
    nudge: float | None = None  # needed at least one nudge
    rejected_submit: float | None = None  # had at least one submit_answer refused
    tool_error: float | None = None  # had at least one failed tool call
    zero_source: float | None = None  # answered with no sources (of answered turns)


class Percentiles(BaseModel):
    p50: int | None = None
    p95: int | None = None


class Thumbs(BaseModel):
    up: int = 0
    down: int = 0


class TraceSummary(BaseModel):
    since: datetime
    until: datetime
    turns: int
    answered: int
    rates: Rates
    stops: dict[str, int]  # turns per stop value
    latency_ms: Percentiles
    tokens: Percentiles  # Usage.total per turn
    thumbs: Thumbs


def window(days: int, now: datetime | None = None) -> tuple[datetime, datetime]:
    until = now or datetime.now(UTC)
    return until - timedelta(days=days), until


def summarize(traces: list[Trace], since: datetime, until: datetime) -> TraceSummary:
    ts = [t for t in traces if since <= t.at <= until]
    answered = [t for t in ts if t.answered]
    stops: dict[str, int] = {}
    for t in ts:
        key = t.stop or "none"
        stops[key] = stops.get(key, 0) + 1

    def share(n: int, of: int) -> float | None:
        return round(n / of, 4) if of else None

    def stop_rate(stop: str) -> float | None:
        return share(stops.get(stop, 0), len(ts))

    rates = Rates(
        no_answer=stop_rate("no_answer"),
        step_limit=stop_rate("step_limit"),
        refusal=stop_rate("refusal"),
        max_tokens=stop_rate("max_tokens"),
        stopped=stop_rate("stopped"),
        error=stop_rate("error"),
        nudge=share(sum(t.nudges > 0 for t in ts), len(ts)),
        rejected_submit=share(sum(bool(t.rejected) for t in ts), len(ts)),
        tool_error=share(sum(bool(t.tool_errors) for t in ts), len(ts)),
        zero_source=share(sum(t.sources == 0 for t in answered), len(answered)),
    )
    ratings = [t.feedback.rating for t in ts if t.feedback]
    return TraceSummary(
        since=since,
        until=until,
        turns=len(ts),
        answered=len(answered),
        rates=rates,
        stops=dict(sorted(stops.items())),
        latency_ms=_percentiles([t.ms for t in ts]),
        tokens=_percentiles([t.usage.total for t in ts if t.stop != "error"]),
        thumbs=Thumbs(up=ratings.count("up"), down=ratings.count("down")),
    )


def _percentiles(values: list[int]) -> Percentiles:
    """Nearest-rank p50 and p95."""
    if not values:
        return Percentiles()
    v = sorted(values)

    def rank(p: float) -> int:
        return v[max(0, math.ceil(p / 100 * len(v)) - 1)]

    return Percentiles(p50=rank(50), p95=rank(95))
