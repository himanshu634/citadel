"""Markdown tables from eval result files, so the numbers published in docs/ are generated.

    uv run python -m agents.evals.report FILE [FILE ...]

Files are grouped by company (the `slug` in each file's meta line). Within a company the first
file is the baseline and the next is compared with it, case by case. Two files of one model and
effort (the same model before and after a change) are labelled "(before)" and "(after)". The
output is a headline table (one row per company), then per company: pass rates by tag, by case,
and the failed runs with the checks that failed. A run that raised (an API or graph error) is
counted apart from a graded failure, because an outage is not an agent miss.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.evals.run import summarize

# Tags that say where a case came from, not what it asks: never a case's group.
_NOT_GROUPS = {"live", "draft"}


@dataclass
class ResultFile:
    path: Path
    meta: dict[str, Any]
    runs: list[dict[str, Any]] = field(default_factory=list)
    suffix: str = ""  # " (before)" / " (after)" when both files of a company share a label

    @property
    def label(self) -> str:
        model = str(self.meta.get("model", "?")).removeprefix("claude-")
        return f"{model} {self.meta.get('effort', '?')}{self.suffix}"

    @property
    def errors(self) -> int:
        return sum(r["error"] is not None for r in self.runs)


def load(path: Path) -> ResultFile:
    lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    meta = next((x for x in lines if x.get("kind") == "meta"), {})
    return ResultFile(path, meta, [x for x in lines if x.get("kind") == "run"])


def group(tags: list[str]) -> str:
    return next((t for t in tags if t not in _NOT_GROUPS), "other")


def _cases(files: list[ResultFile]) -> list[tuple[str, str]]:
    """(case, group) in the order the baseline ran them, then any case only a later file has."""
    seen: dict[str, str] = {}
    for f in files:
        for r in f.runs:
            seen.setdefault(r["case"], group(r.get("tags") or []))
    order = {c: i for i, c in enumerate(files[0].meta.get("cases", []))}
    return sorted(seen.items(), key=lambda kv: order.get(kv[0], len(order)))


def _rate(passed: int, runs: int) -> str:
    return f"{passed}/{runs} ({passed / runs:.0%})" if runs else "–"


def _delta(a: tuple[int, int], b: tuple[int, int]) -> str:
    """Change in pass rate from a to b, in percentage points."""
    if not a[1] or not b[1]:
        return "–"
    d = round((b[0] / b[1] - a[0] / a[1]) * 100)
    return "=" if d == 0 else f"{d:+d} pt"


def _count(f: ResultFile, cases: set[str]) -> tuple[int, int]:
    runs = [r for r in f.runs if r["case"] in cases]
    return sum(r["passed"] for r in runs), len(runs)


def _cell(f: ResultFile, case: str) -> str:
    runs = [r for r in f.runs if r["case"] == case]
    if not runs:
        return "–"
    errors = sum(r["error"] is not None for r in runs)
    return f"{sum(r['passed'] for r in runs)}/{len(runs)}" + (f" ({errors} err)" if errors else "")


def _per_run(f: ResultFile) -> dict[str, float]:
    s = summarize(f.runs).values()
    n = max(sum(x["runs"] for x in s), 1)
    return {k: sum(x[k] for x in s) / n for k in ("steps", "ms", "in", "cached", "out")}


def headline(by_slug: dict[str, list[ResultFile]]) -> str:
    labels = list(dict.fromkeys(f.label for files in by_slug.values() for f in files))
    delta = len(labels) == 2
    lines = [
        "| Company | Cases | " + " | ".join(labels) + (" | Δ |" if delta else " |"),
        "|---|---:|" + "---:|" * (len(labels) + delta),
    ]
    for slug, files in by_slug.items():
        counts = {f.label: _count(f, {r["case"] for r in f.runs}) for f in files}
        row = f"| {slug} | {len(_cases(files))} | "
        row += " | ".join(_rate(*counts[lb]) if lb in counts else "–" for lb in labels)
        if delta:
            row += " | " + (_delta(*[counts[lb] for lb in labels]) if len(counts) == 2 else "–")
        lines.append(row + " |")
    return "\n".join(lines)


def company(slug: str, files: list[ResultFile]) -> str:
    pair = files[:2]
    cases = _cases(files)
    labels = [f.label for f in pair]
    delta = len(pair) == 2
    out = [f"### {slug}", ""]
    for f in pair:
        m = f.meta
        out.append(
            f"- `{f.path.name}`: {m.get('model')}, effort {m.get('effort')}, "
            f"REPEAT {m.get('repeat')}, commit {m.get('commit') or 'not recorded'}, "
            f"started {m.get('started')}"
        )
    out.append("")

    # By tag.
    head = "| Tag | Cases | " + " | ".join(labels) + (" | Δ |" if delta else " |")
    out += [head, "|---|---:|" + "---:|" * (len(labels) + delta)]
    groups = list(dict.fromkeys(g for _, g in cases))
    for g in groups:
        ids = {c for c, cg in cases if cg == g}
        counts = [_count(f, ids) for f in pair]
        row = f"| {g} | {len(ids)} | " + " | ".join(_rate(*c) for c in counts)
        out.append(row + (f" | {_delta(*counts)} |" if delta else " |"))
    ids = {c for c, _ in cases}
    counts = [_count(f, ids) for f in pair]
    row = f"| **all** | {len(ids)} | " + " | ".join(f"**{_rate(*c)}**" for c in counts)
    out.append(row + (f" | **{_delta(*counts)}** |" if delta else " |"))
    out.append("")

    # Totals beyond the pass rate: how many cases always pass, errors, cost per run.
    out += ["| Per run | " + " | ".join(labels) + " |", "|---|" + "---:|" * len(labels)]
    stats = [_per_run(f) for f in pair]
    always = []
    for f in pair:
        s = summarize(f.runs)
        always.append(f"{sum(x['passed'] == x['runs'] for x in s.values())}/{len(s)}")
    rows = [
        ("cases passed every run", always),
        ("runs that errored (API or graph)", [str(f.errors) for f in pair]),
        ("graph tool calls", [f"{s['steps']:.1f}" for s in stats]),
        ("seconds", [f"{s['ms'] / 1000:.1f}" for s in stats]),
        ("input tokens (cached)", [f"{s['in']:,.0f} ({s['cached']:,.0f})" for s in stats]),
        ("output tokens", [f"{s['out']:,.0f}" for s in stats]),
    ]
    out += [f"| {name} | " + " | ".join(vals) + " |" for name, vals in rows]
    out.append("")

    # By case.
    head = "| Case | Tag | " + " | ".join(labels) + (" | Δ |" if delta else " |")
    out += [head, "|---|---|" + "---:|" * (len(labels) + delta)]
    for case, g in cases:
        cells = [_cell(f, case) for f in pair]
        row = f"| `{case}` | {g} | " + " | ".join(cells)
        if delta:
            row += f" | {_delta(*[_count(f, {case}) for f in pair])} |"
        else:
            row += " |"
        out.append(row)
    out.append("")

    # Failed runs, with the checks that failed.
    failed = [(f, r) for f in pair for r in f.runs if not r["passed"]]
    if failed:
        out += ["Failed runs:", ""]
        for f, r in sorted(failed, key=lambda x: (x[1]["case"], x[0].label, x[1]["repeat"])):
            out.append(f"- `{r['case']}` #{r['repeat']} ({f.label}): {_why(r)}")
        out.append("")
    return "\n".join(out)


def _why(run: dict[str, Any]) -> str:
    if run["error"]:
        return f"error: {_short(run['error'])}"
    reasons = []
    for i, t in enumerate(run["turns"], 1):
        for c in t["checks"]:
            if not c["ok"]:
                reason = f"turn {i} {c['name']}: {_short(c['detail'])}"
                if c["name"].startswith("cite_"):
                    reason += f" (cited {', '.join(t.get('sources', [])) or 'nothing'})"
                reasons.append(reason)
    return "; ".join(reasons) or "failed"


def _short(text: str, limit: int = 140) -> str:
    text = " ".join(str(text).split()).replace("|", "\\|")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render(paths: list[Path]) -> str:
    by_slug: dict[str, list[ResultFile]] = {}
    for p in paths:
        f = load(p)
        by_slug.setdefault(f.meta.get("slug") or p.parent.name, []).append(f)
    for files in by_slug.values():
        if len(files) > 1 and files[0].label == files[1].label:
            files[0].suffix, files[1].suffix = " (before)", " (after)"
    parts = [headline(by_slug), ""]
    parts += [company(slug, files) for slug, files in by_slug.items()]
    return "\n".join(parts).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m agents.evals.report", description=__doc__.split("\n\n")[0]
    )
    p.add_argument("files", nargs="+", type=Path, help="result files; per company, baseline first")
    args = p.parse_args(argv)
    missing = [str(f) for f in args.files if not f.is_file()]
    if missing:
        print(f"no such file: {', '.join(missing)}", file=sys.stderr)
        return 2
    sys.stdout.write(render(args.files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
