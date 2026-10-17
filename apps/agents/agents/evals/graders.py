"""Deterministic checks for one answered turn. Pure: no model, no graph.

`check_answer` in the loop already guarantees every cited uid came from a tool result, so these
checks don't re-test that; they test whether the right nodes were cited, the right tools ran,
and the text says what it should.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from agents.evals.cases import Expect


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
    failed: list[str] | None = None,
) -> list[Check]:
    """`gold` holds the resolved uids for cite_any / cite_all / cite_none; `cited` is the
    answer's sources and path; `tools` the graph tools called, in order (repeats kept); `failed`
    the name of each call that returned an error. tools_any / tools_all count only calls that
    worked (a semantic_search that raised found nothing); tools_none and max_steps count every
    call."""
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
    worked = Counter(tools) - Counter(failed or [])
    if expect.tools_any:
        hit = sorted(set(worked) & set(expect.tools_any))
        out.append(Check("tools_any", bool(hit), _show(hit or expect.tools_any, hit)))
    if expect.tools_all:
        miss = [t for t in expect.tools_all if t not in worked]
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
