"""Backfill the chat history from LangGraph's checkpoints, for threads asked before it existed.

Why: the history (`history.py`) is written as a run happens, so chats asked earlier exist only
as checkpoints in agent_<slug>. A thread's latest checkpoint still holds every message in
Anthropic block format, plus (for runs since the Ask page's walk) the `trace` channel with each
tool call's rows and subgraph. This module replays that state as the events a live run would
have sent (`start`, `llm`, `step_done`, the answer) into a `Recorder`, so a backfilled chat is
written by exactly the same code as a live one.

What it can and cannot recover:
- Questions, Claude's text and thinking, every tool call and its input, failed calls, the
  accepted answer and its sources: always (from the messages).
- A call's rows, nodes and timing: from `trace` when the run had it, otherwise rebuilt from the
  tool result's JSON (`walk.subgraph`), with no timing.
- When each turn happened, its trace id (thumbs) and how it stopped: from the turn's line in
  data/traces/<slug>.jsonl when there is one (matched by thread and question, in order);
  otherwise every turn gets the time of the thread's last checkpoint.
- Tokens per response: when the `usage` channel has one entry per saved response.
Threads that already have history are skipped, so a re-run only adds what is missing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from brain.agents.ask import Answer, Source, answer_out
from brain.agents.history import GraphChatStore, Recorder
from brain.agents.loop import SUBMIT, llm_event
from brain.agents.toolset import _collect_nodes
from brain.agents.traces import Trace, TraceStore
from brain.agents.walk import preview_rows, subgraph

log = logging.getLogger(__name__)
PREFIX = "Company: "  # how `ask._run` opens every question


@dataclass
class BackfillReport:
    threads: list[str] = field(default_factory=list)  # backfilled
    turns: int = 0
    skipped: list[str] = field(default_factory=list)  # no question found in the checkpoint


def backfill(slug: str, store: GraphChatStore, saver: Any, traces: TraceStore) -> BackfillReport:
    """Write history for every thread that has checkpoints and no history yet."""
    report = BackfillReport()
    by_thread: dict[str, list[Trace]] = {}
    for t in traces.read():
        by_thread.setdefault(t.thread_id, []).append(t)
    for thread_id in store.checkpoint_threads():
        saved = saver.get_tuple({"configurable": {"thread_id": thread_id}})
        if saved is None:
            continue
        turns = replay(
            thread_id,
            saved.checkpoint.get("channel_values") or {},
            _ms(saved.checkpoint.get("ts")),
            by_thread.get(thread_id, []),
        )
        if not turns:
            report.skipped.append(thread_id)
            continue
        for turn in turns:
            rec = Recorder(store, turn.question, clock=lambda at=turn.at: at)
            for event in turn.events:
                rec.on(event)
            if turn.error:
                rec.fail(turn.error, turn.trace_id, ms=turn.ms)
            else:
                rec.answer(turn.answer, turn.model, ms=turn.ms)
        report.threads.append(thread_id)
        report.turns += len(turns)
    return report


@dataclass
class Turn:
    question: str
    at: int  # epoch ms the turn is dated
    ms: int | None
    events: list[dict[str, Any]]
    answer: dict[str, Any]  # the `answer` event
    model: str | None
    trace_id: str | None
    error: str | None


def replay(thread_id: str, values: dict[str, Any], last_ms: int, traces: list[Trace]) -> list[Turn]:
    """A thread's state as the events of its turns, oldest first."""
    messages: list[dict[str, Any]] = values.get("messages") or []
    trace_by_id = {t["id"]: t for t in values.get("trace") or []}
    seen: dict[str, dict[str, Any]] = values.get("seen") or {}
    usage: list[dict[str, Any]] = values.get("usage") or []
    replies = [m for m in messages if m["role"] == "assistant"]
    usage_of = (
        dict(zip(map(id, replies), usage, strict=False)) if len(usage) == len(replies) else {}
    )

    # Split the messages into turns at each question.
    spans: list[tuple[str, list[dict[str, Any]]]] = []
    for m in messages:
        q = _question(m)
        if q is not None:
            spans.append((q, []))
        elif spans:
            spans[-1][1].append(m)

    out: list[Turn] = []
    pending = list(traces)
    for question, rest in spans:
        line = next((t for t in pending if t.question == question), None)
        if line is not None:
            pending.remove(line)
        model = (line.model if line else None) or values.get("model")
        out.append(
            _turn(thread_id, question, rest, line, last_ms, trace_by_id, seen, usage_of, model)
        )
    return out


def _turn(thread_id, question, rest, line, last_ms, trace_by_id, seen, usage_of, model) -> Turn:
    results = {
        b["tool_use_id"]: b
        for m in rest
        if m["role"] == "user"
        for b in m["content"]
        if b.get("type") == "tool_result"
    }
    events: list[dict[str, Any]] = [{"kind": "start", "thread_id": thread_id}]
    steps: list[dict[str, Any]] = []  # graph steps of this turn, in order (for sources)
    accepted: dict[str, Any] | None = None
    seq = n = 0
    for m in rest:
        if m["role"] != "assistant":
            continue
        seq += 1
        usage = usage_of.get(id(m)) or {}
        event = llm_event(m["content"], _Msg(model, usage), 0, SUBMIT)
        event["ms"] = None
        events.append({**event, "seq": seq})
        for call in event["calls"]:
            if call["kind"] not in ("graph", "submit"):
                continue
            result = results.get(call["id"])
            if call["kind"] == "submit":
                ok = result is not None and not result.get("is_error")
                if ok:
                    accepted = call["input"]
                events.append(_done(call, seq, None, {
                    "error": None if ok else _text(result) or "Not run: the answer ended first.",
                }))  # fmt: skip
                continue
            n += 1
            step = trace_by_id.get(call["id"]) or _rebuilt(call, result)
            steps.append(step)
            events.append(_done(call, seq, n, step))

    error = line.error if line and line.stop == "error" else None
    stop = (line.stop if line else None) or ("tool_use" if accepted else "no_answer")
    answer = _answer(question, thread_id, accepted, stop, model, seen, steps)
    trace_id = line.id if line else None
    at = int(line.at.timestamp() * 1000) if line else last_ms
    return Turn(question, at, line.ms if line else None, events, answer_out(answer, trace_id),
                model, trace_id, error)  # fmt: skip


def _done(call: dict[str, Any], seq: int, n: int | None, step: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "step_done",
        "id": call["id"],
        "tool": call["tool"],
        "input": call["input"],
        "call": seq,
        "n": n,
        "ms": step.get("ms"),
        "count": step.get("count"),
        "error": step.get("error"),
        "rows": step.get("rows") or [],
        "nodes": step.get("nodes") or [],
        "rels": step.get("rels") or [],
        "uids": step.get("uids") or [],
    }


def _rebuilt(call: dict[str, Any], result: dict[str, Any] | None) -> dict[str, Any]:
    """A step from its tool result alone (runs from before the `trace` channel)."""
    if result is None:
        return {"error": "Not run: the answer ended first."}
    text = _text(result)
    if result.get("is_error"):
        try:
            return {"error": str(json.loads(text).get("error") or text)}
        except (ValueError, AttributeError):
            return {"error": text}
    try:
        rows = json.loads(text)["rows"]
    except (ValueError, KeyError, TypeError):
        return {"count": None}  # a result cut for length: nothing to read back
    found: dict[str, dict[str, Any]] = {}
    _collect_nodes(rows, found)
    try:
        nodes, rels = subgraph(call["tool"], call["input"], rows)
    except Exception:  # params without their defaults; the walk is a nicety here
        nodes, rels = [], []
    return {"count": len(rows), "rows": preview_rows(rows), "nodes": nodes, "rels": rels,
            "uids": sorted(found)}  # fmt: skip


def _answer(question, thread_id, accepted, stop, model, seen, steps) -> Answer:
    drawn = {nd["uid"]: nd for s in steps for nd in s.get("nodes", ())}

    def source(uid: str) -> Source:
        node, other = seen.get(uid, {}), drawn.get(uid, {})
        step = next((i for i, s in enumerate(steps, 1) if uid in s.get("uids", ())), None)
        return Source(uid=uid, title=node.get("title") or other.get("title"),
                      url=node.get("url") or other.get("url"),
                      label=node.get("label") or other.get("label"), step=step)  # fmt: skip

    return Answer(
        question=question,
        thread_id=thread_id,
        text=accepted["answer"] if accepted else None,
        sources=[source(u) for u in accepted["sources"]] if accepted else [],
        path=[source(u) for u in accepted.get("path", [])] if accepted else [],
        stop=stop,
        model=model,
    )


def _question(m: dict[str, Any]) -> str | None:
    if m["role"] != "user" or not m["content"]:
        return None
    first = m["content"][0]
    if first.get("type") != "text" or not first["text"].startswith(PREFIX):
        return None
    return first["text"].split("\n\n", 1)[-1]


def _text(block: dict[str, Any] | None) -> str:
    if block is None:
        return ""
    body = block.get("content")
    if isinstance(body, list):
        return "\n".join(c.get("text", "") for c in body if isinstance(c, dict))
    return str(body or "")


def _ms(ts: str | None) -> int:
    try:
        return int(datetime.fromisoformat(ts).timestamp() * 1000) if ts else 0
    except ValueError:
        return 0


class _Msg:
    """What `llm_event` reads from an API message, rebuilt from a saved one."""

    def __init__(self, model: str | None, usage: dict[str, Any]):
        self.model = model
        self.stop_reason = None
        self.usage = _Usage(usage)


class _Usage:
    def __init__(self, u: dict[str, Any]):
        self.input_tokens = u.get("input_tokens", 0)
        self.output_tokens = u.get("output_tokens", 0)
        self.cache_read_input_tokens = u.get("cache_read_input_tokens", 0)
        self.cache_creation_input_tokens = u.get("cache_creation_input_tokens", 0)
