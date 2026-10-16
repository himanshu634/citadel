"""Turn thumbs-down answers from live use into draft eval cases.

    uv run python -m evals.drafts --slug acme [--days 30] [--write]

Why: the offline cases should grow from the questions the brain actually got wrong. Each turn
with a thumbs down in data/traces/<slug>.jsonl (`brain.agents.traces`) becomes one case: the
earlier turns of its thread (so a follow-up like "and who reviews it?" keeps its meaning) and
then the bad turn. Nobody knows the right answer yet, so a draft only expects an answer; the bad
answer, what it cited and the thumbs note go in comments above it for whoever writes the real
`expect`. Drafts are tagged `draft`, which a plain `make eval` skips; remove the tag once the
case is finished.

Without --write the drafts are printed. --write appends the new ones to evals/cases/<slug>.yaml
(ids `fb-<trace id>`; a case already in the file is not added again).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from brain.agents.traces import Trace, TraceStore

from evals import cases as cases_mod
from evals.cases import DRAFT, Case

ANSWER_CHARS = 400  # of the bad answer, quoted in the draft's comments
HEADER = "# --- drafts from thumbs-down answers (evals/drafts.py) ---"


def thumbs_down(traces: list[Trace]) -> list[Trace]:
    return [t for t in traces if t.feedback and t.feedback.rating == "down"]


def draft(bad: Trace, traces: list[Trace]) -> tuple[dict, list[str]]:
    """The case (as it goes in the YAML) for one thumbs-down turn, and the comment lines that go
    above it."""
    earlier = sorted(
        (t for t in traces if t.thread_id == bad.thread_id and t.at < bad.at and t.id != bad.id),
        key=lambda t: t.at,
    )
    note = bad.feedback.note if bad.feedback else None
    case = {
        "id": f"fb-{bad.id}",
        "tags": [DRAFT, "feedback"],
        "why": note or "Thumbs down on the Ask page; say what a good answer must contain.",
        "turns": [{"question": t.question} for t in earlier]
        + [{"question": bad.question, "expect": {"answered": True}}],
    }
    Case.model_validate(case)
    day = bad.at.astimezone(UTC).date().isoformat()
    comments = [
        f"thumbs down {day} on trace {bad.id} (thread {bad.thread_id}, {bad.model}, via {bad.via})",
        f"it stopped with {bad.stop}; tools: {', '.join(bad.tools) or 'none'}",
    ]
    if bad.tool_errors:
        comments.append(f"failed tool calls: {'; '.join(bad.tool_errors)}")
    if bad.rejected:
        comments.append(f"rejected submits: {len(bad.rejected)}")
    if bad.text:
        text = " ".join(bad.text.split())
        cut = text[:ANSWER_CHARS] + ("..." if len(text) > ANSWER_CHARS else "")
        comments.append(f"its answer: {cut}")
    if bad.cited:
        comments.append(f"it cited: {', '.join(bad.cited)}")
    comments.append("TODO: write expect (cite_any / text_all / ...), then drop the draft tag.")
    return case, comments


def render(drafts: list[tuple[dict, list[str]]]) -> str:
    """YAML for the case file: per draft a comment block, then the case as a one-item list."""
    return "\n".join(
        "\n".join(f"# {' '.join(c.split())}" for c in comments)  # one line each, whatever it holds
        + "\n"
        + yaml.safe_dump([case], sort_keys=False, allow_unicode=True, width=100)
        for case, comments in drafts
    )


def build(slug: str, days: int | None, known: set[str]) -> list[tuple[dict, list[str]]]:
    since = datetime.now(UTC) - timedelta(days=days) if days else None
    traces = TraceStore(slug).read()  # the whole file: earlier turns may predate the window
    bad = [t for t in thumbs_down(traces) if since is None or t.at >= since]
    return [d for d in (draft(t, traces) for t in bad) if d[0]["id"] not in known]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m evals.drafts", description=__doc__.split("\n\n")[0])
    p.add_argument("--slug", required=True)
    p.add_argument("--days", type=int, help="only thumbs-down turns from the last N days")
    p.add_argument("--write", action="store_true", help="append to evals/cases/<slug>.yaml")
    p.add_argument("--cases", type=Path, help=argparse.SUPPRESS)  # tests: another case file
    args = p.parse_args(argv)

    path = args.cases or cases_mod.CASES_DIR / f"{args.slug}.yaml"
    known = {c.id for c in cases_mod.load(args.slug, path)} if path.exists() else set()
    drafts = build(args.slug, args.days, known)
    if not drafts:
        print(f"no new thumbs-down turns for {args.slug}", file=sys.stderr)
        return 0
    text = render(drafts)
    if not args.write:
        print(text)
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text() if path.exists() else ""
    head = "" if HEADER in old else HEADER + "\n\n"
    sep = "" if not old or old.endswith("\n\n") else ("\n" if old.endswith("\n") else "\n\n")
    # Check the whole new file before it replaces the old one: a broken case file stops every
    # eval of this company.
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(old + sep + head + text)
    try:
        cases_mod.load(args.slug, tmp)
    except Exception:
        tmp.unlink()
        raise
    os.replace(tmp, path)
    print(f"added {len(drafts)} draft cases to {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
