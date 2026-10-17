"""Offline policies: deterministic stand-ins for Claude, one per job (ground rule 6).

Why: simulations and tests must run with no API key, and they should exercise the real path. A
policy is a pure function of the run's context and the tool results so far; `ScriptedClient`
plays it through the real brain loop, answering with the same message shapes the Messages API
returns (like `agents/offline.py`). So the toolset, the grounding check and the store's guards
all run exactly as they do for Claude.

    def policy(context, results):
        if not results.called("list_systems"):
            return [("list_systems", {})]           # tool calls for this turn
        return {"task": ..., "cites": [...]}        # the submit input: ends the run
        return None                                 # no decision: the run ends with no answer
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any

from anthropic.types.beta import BetaTextBlock, BetaToolUseBlock, BetaUsage

MODEL = "offline-policy"
_CONTEXT = re.compile(r"<context>\n(.*)\n</context>", re.S)

Call = tuple[str, dict[str, Any]]


@dataclass
class Results:
    """Tool results seen so far in this run, in call order."""

    calls: list[tuple[str, dict[str, Any], list[dict[str, Any]] | None]] = field(
        default_factory=list
    )  # (tool, input, rows); rows is None when the call failed

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def rows(self, name: str, **match: Any) -> list[dict[str, Any]]:
        """Rows of every successful call to `name` (whose input has `match`), in order."""
        out: list[dict[str, Any]] = []
        for tool, inp, rows in self.calls:
            if tool == name and rows and all(inp.get(k) == v for k, v in match.items()):
                out += rows
        return out


Policy = Callable[[dict[str, Any], Results], "list[Call] | dict[str, Any] | None"]


@dataclass
class _Message:
    content: list[Any]
    stop_reason: str = "tool_use"
    stop_details: None = None
    model: str = MODEL
    usage: BetaUsage = field(default_factory=lambda: BetaUsage(input_tokens=0, output_tokens=0))


@dataclass
class _Stream:
    message: _Message

    def get_final_message(self) -> _Message:
        return self.message


class ScriptedClient:
    """Plays one policy through the brain loop (`client.beta.messages.stream(...)`)."""

    def __init__(self, policy: Policy) -> None:
        self.policy = policy
        self.beta = self
        self.messages = self
        self.calls = 0

    def stream(self, *, messages: list[dict[str, Any]], tools: list[dict], **_: Any):
        self.calls += 1
        return nullcontext(_Stream(self._reply(messages, tools[-1]["name"])))

    def _reply(self, messages: list[dict[str, Any]], submit: str) -> _Message:
        context = _context(messages[0])
        results, rejected = _results(messages, submit)
        if rejected is not None:  # the loop refused the submit: a policy does not retry
            text = BetaTextBlock(type="text", text=f"Could not submit: {rejected}")
            return _Message(content=[text], stop_reason="end_turn")
        out = self.policy(context, results)
        if out is None:  # no decision: plain text, so the loop nudges once and then gives up
            text = BetaTextBlock(type="text", text="No decision: nothing in the graph to cite.")
            return _Message(content=[text], stop_reason="end_turn")
        if isinstance(out, dict):
            calls: list[Call] = [(submit, out)]
        else:
            calls = out
        blocks = [
            BetaToolUseBlock(type="tool_use", id=f"p{self.calls}_{i}", name=name, input=inp)
            for i, (name, inp) in enumerate(calls)
        ]
        return _Message(content=blocks)


def _context(first: dict[str, Any]) -> dict[str, Any]:
    text = "".join(b.get("text", "") for b in first["content"] if b.get("type") == "text")
    m = _CONTEXT.search(text)
    return json.loads(m.group(1)) if m else {}


def _results(messages: list[dict[str, Any]], submit: str) -> tuple[Results, str | None]:
    uses: dict[str, tuple[str, dict[str, Any]]] = {}
    results = Results()
    rejected = None
    for m in messages:
        for b in m["content"]:
            if b.get("type") == "tool_use":
                uses[b["id"]] = (b["name"], b.get("input") or {})
            elif b.get("type") == "tool_result":
                name, inp = uses.get(b["tool_use_id"], ("?", {}))
                if name == submit:
                    rejected = b["content"] if b.get("is_error") else None
                    continue
                rows = None
                if not b.get("is_error"):
                    try:
                        rows = json.loads(b["content"]).get("rows", [])
                    except json.JSONDecodeError:  # a cut, oversized result
                        rows = []
                results.calls.append((name, inp, rows))
    return results, rejected


# --- small helpers shared by the policies ------------------------------------------------------

_WORD = re.compile(r"[a-z0-9]+")


def words(text: str | None) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if len(w) > 2}


def first_line(text: str | None) -> str:
    return (text or "").strip().splitlines()[0] if (text or "").strip() else ""


def uniq(items: list[str]) -> list[str]:
    return list(dict.fromkeys(i for i in items if i))
