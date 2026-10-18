"""A scripted stand-in for Claude, for `agents chat --offline`.

Why: anyone can check the wiring without an API key. The real agent graph, toolset, graph tools and
FalkorDB checkpointer all run; only the model is replaced by two fixed replies:
1. call `list_systems`;
2. submit an answer that names the systems and cites the first one.
It answers the same message shapes the Messages API returns, so the brain loop can't tell. The
script never calls `ask_archivist` (in Ask's toolset), so no Archivist runs and no key is needed.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any

from anthropic.types.beta import BetaToolUseBlock, BetaUsage

from agents.loop import SUBMIT

MODEL = "offline-script"


@dataclass
class _Message:
    content: list[Any]
    stop_reason: str = "tool_use"
    stop_details: None = None
    model: str = MODEL
    usage: BetaUsage = field(default_factory=lambda: BetaUsage(input_tokens=0, output_tokens=0))


class OfflineClient:
    def __init__(self) -> None:
        self.beta = self  # the loop calls client.beta.messages.stream(...)
        self.messages = self
        self.calls = 0

    def stream(self, *, messages: list[dict[str, Any]], **_: Any):
        self.calls += 1
        return nullcontext(_Stream(_reply(messages, self.calls)))


@dataclass
class _Stream:
    message: _Message

    def get_final_message(self) -> _Message:
        return self.message


def _reply(messages: list[dict[str, Any]], n: int) -> _Message:
    last = messages[-1]["content"]
    results = [b for b in last if b.get("type") == "tool_result" and not b.get("is_error")]
    if not results:
        use = BetaToolUseBlock(type="tool_use", id=f"offline_{n}", name="list_systems", input={})
        return _Message(content=[use])
    rows = json.loads(results[-1]["content"]).get("rows", [])
    uids = [r.get("system_uid") or r.get("uid") for r in rows]
    names = [r.get("system") or r.get("name") or u for r, u in zip(rows, uids, strict=True)]
    if uids and uids[0]:
        answer = f"The graph has {len(rows)} systems: {', '.join(map(str, names))} [1]."
        sources = [uids[0]]
    else:
        answer, sources = "The graph has no systems yet.", []
    submit = BetaToolUseBlock(
        type="tool_use",
        id=f"offline_{n}",
        name=SUBMIT,
        input={"answer": answer, "sources": sources, "path": []},
    )
    return _Message(content=[submit])
