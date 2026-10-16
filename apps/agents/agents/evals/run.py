"""Run eval cases against brain_<slug> with the real agent, grade them, record the results.

    uv run python -m evals --slug synthetic [--case ID|TAG ...] [--repeat N] [--jobs N]
        [--model M] [--effort E] [--baseline data/evals/synthetic/<run>.jsonl]

Each case runs `repeat` times (models are not deterministic, so a case reports a pass rate, not
a verdict). Turns of one case share a thread (in-memory checkpointer), so follow-ups see the
earlier turns. Results go to data/evals/<slug>/<utc time>-<model>-<effort>.jsonl: a `meta` line,
then one `run` line per case repeat. `--baseline` prints per-case pass-rate changes against an
earlier file.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anthropic
from brain.agents.ask import ask_traced
from brain.agents.loop import SUBMIT
from brain.agents.toolset import Toolset, graph_toolset
from brain.agents.traces import step_summary
from brain.config import REPO_ROOT, get_settings
from langgraph.checkpoint.memory import InMemorySaver

from evals import cases as cases_mod
from evals.cases import Case, GoldResolver
from evals.graders import grade

OUT_DIR = REPO_ROOT / "data" / "evals"


def run_case(
    case: Case,
    slug: str,
    gold: GoldResolver,
    *,
    repeat: int = 0,
    client: anthropic.Anthropic | None = None,
    toolset: Toolset | None = None,
) -> dict[str, Any]:
    """One run of one case: every turn asked in one thread, each graded on its own."""
    thread = f"eval-{case.id}-{repeat}-{uuid.uuid4().hex[:6]}"
    saver = InMemorySaver()
    turns: list[dict[str, Any]] = []
    error = None
    for turn in case.turns:
        expected = gold.resolve(turn.expect)
        started = time.perf_counter()
        try:
            answer, steps = ask_traced(
                slug, turn.question, thread, client=client, toolset=toolset, checkpointer=saver
            )
        except Exception as e:  # an API or graph failure fails this run, not the whole eval
            error = f"{type(e).__name__}: {e}"
            break
        ms = round((time.perf_counter() - started) * 1000)
        summary = step_summary(steps, SUBMIT)
        cited = [s.uid for s in answer.sources] + [p.uid for p in answer.path]
        checks = grade(turn.expect, expected, text=answer.text, cited=cited, tools=summary["tools"])
        turns.append(
            {
                "question": turn.question,
                "passed": all(c.ok for c in checks),
                "checks": [asdict(c) for c in checks],
                "text": answer.text,
                "sources": [s.uid for s in answer.sources],
                "path": [p.uid for p in answer.path],
                "stop": answer.stop,
                "model": answer.model,
                "usage": answer.usage,
                "ms": ms,
                **summary,
            }
        )
    passed = error is None and len(turns) == len(case.turns) and all(t["passed"] for t in turns)
    return {
        "kind": "run",
        "case": case.id,
        "tags": case.tags,
        "repeat": repeat,
        "passed": passed,
        "error": error,
        "turns": turns,
    }


def run_all(
    cases: list[Case],
    slug: str,
    *,
    repeat: int = 1,
    jobs: int = 4,
    client: anthropic.Anthropic | None = None,
    toolset: Toolset | None = None,
    on_result: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    toolset = toolset or graph_toolset()
    gold = GoldResolver(slug, toolset.run)
    for case in cases:  # resolve every gold ref up front: a bad one stops the run before any spend
        for turn in case.turns:
            gold.resolve(turn.expect)
    work = [(c, i) for c in cases for i in range(repeat)]

    def one(item: tuple[Case, int]) -> dict[str, Any]:
        result = run_case(item[0], slug, gold, repeat=item[1], client=client, toolset=toolset)
        if on_result:
            on_result(result)
        return result

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        return list(pool.map(one, work))


# --- reporting --------------------------------------------------------------------------------


def summarize(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per case: passes / runs, graph tool calls, rejected answers and tokens. `in` counts the
    whole prompt (uncached + cache reads + cache writes); `cached` is the cache-read part."""
    out: dict[str, dict[str, Any]] = {}
    for r in results:
        s = out.setdefault(
            r["case"],
            {"runs": 0, "passed": 0, "steps": 0, "rejected": 0, "tool_errors": 0, "in": 0,
             "cached": 0, "out": 0,
             "ms": 0, "errors": 0},
        )  # fmt: skip
        s["runs"] += 1
        s["passed"] += r["passed"]
        s["errors"] += r["error"] is not None
        for t in r["turns"]:
            s["steps"] += len(t["tools"])
            s["rejected"] += len(t["rejected"])
            s["tool_errors"] += len(t["tool_errors"])
            u = t["usage"]
            s["cached"] += u.get("cache_read_input_tokens", 0)
            s["in"] += sum(u.get(k, 0) for k in _INPUT_KEYS)
            s["out"] += u.get("output_tokens", 0)
            s["ms"] += t["ms"]
    return out


def report(results: list[dict[str, Any]], baseline: dict[str, dict[str, Any]] | None) -> str:
    summary = summarize(results)
    lines = [
        f"{'case':<28} {'pass':>6} {'steps':>6} {'rej':>4} {'terr':>5} {'in':>7} {'cached':>7} "
        f"{'out':>6} {'sec':>6}" + ("  vs baseline" if baseline else "")
    ]
    for case, s in summary.items():
        n = s["runs"]
        row = (
            f"{case:<28} {s['passed']:>3}/{n:<2} {s['steps'] / n:>6.1f} {s['rejected']:>4} "
            f"{s['tool_errors']:>5} {s['in'] // n:>7} {s['cached'] // n:>7} "
            f"{s['out'] // n:>6} {s['ms'] / n / 1000:>6.1f}"
        )
        if baseline:
            row += "  " + _delta(s, baseline.get(case))
        lines.append(row)
    runs = sum(s["runs"] for s in summary.values())
    passed = sum(s["passed"] for s in summary.values())
    tin = sum(s["in"] for s in summary.values())
    tcached = sum(s["cached"] for s in summary.values())
    tout = sum(s["out"] for s in summary.values())
    lines.append(
        f"\n{passed}/{runs} runs passed ({passed / max(runs, 1):.0%}); tokens per run above, "
        f"total in {tin} (cached {tcached}), out {tout}"
    )
    failed = [r for r in results if not r["passed"]]
    for r in failed:
        lines.append(
            f"\nFAIL {r['case']} #{r['repeat']}" + (f": {r['error']}" if r["error"] else "")
        )
        for i, t in enumerate(r["turns"], 1):
            for c in t["checks"]:
                if not c["ok"]:
                    lines.append(f"  turn {i} {c['name']}: {c['detail']}")
            if not t["passed"]:
                lines.append(f"  turn {i} tools: {t['tools']}  stop: {t['stop']}")
                if t["text"]:
                    lines.append(
                        "  turn {} answer: {}".format(i, t["text"][:300].replace("\n", " "))
                    )
    return "\n".join(lines)


_INPUT_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def _delta(now: dict[str, Any], before: dict[str, Any] | None) -> str:
    if not before:
        return "new"
    a = now["passed"] / now["runs"]
    b = before["passed"] / before["runs"]
    if abs(a - b) < 1e-9:
        return "="
    return f"{'+' if a > b else '-'}{abs(a - b):.0%}{'  REGRESSED' if a < b else ''}"


def load_results(path: Path) -> list[dict[str, Any]]:
    lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [r for r in lines if r.get("kind") == "run"]


def write(results: list[dict[str, Any]], meta: dict[str, Any], slug: str) -> Path:
    out = OUT_DIR / slug
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = out / f"{stamp}-{meta['model']}-{meta['effort']}.jsonl"
    with path.open("w") as fh:
        fh.write(json.dumps({"kind": "meta", **meta}) + "\n")
        for r in results:
            fh.write(json.dumps(r, default=str) + "\n")
    return path


# --- CLI --------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m evals", description=__doc__.split("\n\n")[0])
    p.add_argument("--slug", default="synthetic")
    p.add_argument("--case", action="append", default=[], help="case id or tag (repeatable)")
    p.add_argument("--repeat", type=int, default=1, help="runs per case")
    p.add_argument("--jobs", type=int, default=4, help="runs in parallel")
    p.add_argument("--model", help="override ANTHROPIC_MODEL")
    p.add_argument("--effort", help="override ANTHROPIC_EFFORT")
    p.add_argument("--baseline", type=Path, help="an earlier results file to compare with")
    p.add_argument("--list", action="store_true", help="list the cases and exit")
    args = p.parse_args(argv)

    if args.model:
        os.environ["ANTHROPIC_MODEL"] = args.model
    if args.effort:
        os.environ["ANTHROPIC_EFFORT"] = args.effort
    get_settings.cache_clear()
    settings = get_settings()

    cases = cases_mod.select(cases_mod.load(args.slug), args.case)
    if args.list:
        for c in cases:
            print(f"{c.id:<28} {','.join(c.tags):<20} {c.why}")
        return 0
    if not cases:
        print(f"no cases match {args.case}", file=sys.stderr)
        return 2
    problem = _not_ready(args.slug)
    if problem:
        print(problem, file=sys.stderr)
        return 2

    meta = {
        "slug": args.slug,
        "model": settings.anthropic_model,
        "effort": settings.anthropic_effort,
        "repeat": args.repeat,
        "cases": [c.id for c in cases],
        "started": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    print(
        f"{len(cases)} cases x {args.repeat} on brain_{args.slug} "
        f"({meta['model']}, effort {meta['effort']})",
        file=sys.stderr,
    )

    def progress(r: dict[str, Any]) -> None:
        print(f"  {'pass' if r['passed'] else 'FAIL'}  {r['case']} #{r['repeat']}", file=sys.stderr)

    results = run_all(cases, args.slug, repeat=args.repeat, jobs=args.jobs, on_result=progress)
    path = write(results, meta, args.slug)
    baseline = summarize(load_results(args.baseline)) if args.baseline else None
    print(report(results, baseline))
    print(f"\nresults: {path.relative_to(REPO_ROOT)}")
    return 0 if all(r["passed"] for r in results) else 1


def _not_ready(slug: str) -> str | None:
    from brain import db

    if not get_settings().anthropic_api_key and not os.environ.get("ANTHROPIC_API_KEY"):
        return "ANTHROPIC_API_KEY is not set (.env); evals call the API."
    try:
        if not db.graph_exists(slug):
            return f"brain_{slug} is not loaded (make synthetic, or make sync SLUG={slug})."
    except Exception as e:
        return f"FalkorDB is not reachable (make up): {e}"
    return None
