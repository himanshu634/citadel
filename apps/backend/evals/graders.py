"""Deterministic checks for one answered turn. Pure: no model, no graph.

`check_answer` in the loop already guarantees every cited uid came from a tool result, so these
checks don't re-test that; they test whether the right nodes were cited, the right tools ran,
and the text says what it should.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from evals.cases import Expect


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str = ""


def grade(
    expect: Expect,
    gold: dict[str, list[str]],
    *,
    text: str | None,
    cited: list[str],
    tools: list[str],
) -> list[Check]:
    """`gold` holds the resolved uids for cite_any / cite_all / cite_none; `cited` is the
    answer's sources and path; `tools` the graph tools that ran, in order (repeats kept)."""
    out: list[Check] = []
    answered = text is not None
    if expect.answered != answered:
        out.append(Check("answered", False, f"expected answered={expect.answered}"))
        return out  # nothing else can be graded on a missing answer
    if expect.answered:
        out.append(Check("answered", True))
    body = (text or "").lower()
    got = set(cited)

    if gold["cite_any"]:
        hit = sorted(got & set(gold["cite_any"]))
        out.append(Check("cite_any", bool(hit), _show(hit or gold["cite_any"], hit)))
    if gold["cite_all"]:
        miss = [u for u in gold["cite_all"] if u not in got]
        out.append(Check("cite_all", not miss, f"missing {miss}" if miss else ""))
    if gold["cite_none"]:
        bad = sorted(got & set(gold["cite_none"]))
        out.append(Check("cite_none", not bad, f"cited {bad}" if bad else ""))

    ran = set(tools)
    if expect.tools_any:
        hit = sorted(ran & set(expect.tools_any))
        out.append(Check("tools_any", bool(hit), _show(hit or expect.tools_any, hit)))
    if expect.tools_all:
        miss = [t for t in expect.tools_all if t not in ran]
        out.append(Check("tools_all", not miss, f"missing {miss}" if miss else ""))
    if expect.tools_none:
        bad = sorted(ran & set(expect.tools_none))
        out.append(Check("tools_none", not bad, f"ran {bad}" if bad else ""))

    if expect.text_any:
        hit = [s for s in expect.text_any if s.lower() in body]
        out.append(Check("text_any", bool(hit), _show(hit or expect.text_any, hit)))
    if expect.text_all:
        miss = [s for s in expect.text_all if s.lower() not in body]
        out.append(Check("text_all", not miss, f"missing {miss}" if miss else ""))
    if expect.text_none:
        bad = [s for s in expect.text_none if s.lower() in body]
        out.append(Check("text_none", not bad, f"says {bad}" if bad else ""))
    if expect.text_re:
        m = re.search(expect.text_re, text or "", re.I)
        out.append(Check("text_re", bool(m), repr(m.group(0)) if m else "no match"))

    if expect.max_steps is not None:
        n = len(tools)
        out.append(Check("max_steps", n <= expect.max_steps, f"{n}/{expect.max_steps}"))
    return out


def _show(items: list[str], hit: list[str]) -> str:
    return f"{'found' if hit else 'none of'} {items}"


def step_summary(steps: list[dict[str, Any]], submit: str) -> dict[str, Any]:
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
