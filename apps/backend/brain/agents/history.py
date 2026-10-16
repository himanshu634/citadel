"""Chat history: every Ask conversation kept in the graph, so the Ask page can list and reopen it.

Why: LangGraph's checkpoints (agent_<slug>) hold a thread's messages for the agent to resume,
but as encoded blobs with no title or time, so nothing can list or show them. The history is a
readable copy, written beside them in agent_<slug> as the run happens:

    (:Thread {id, title, created_at, updated_at, turn_count, last_status})
      -[:HAS_TURN]->  (:Turn {uid, n, question, status, answer_json, trace_id, ...})
      -[:HAS_CALL]->  (:LLMCall {seq, text, thinking, model, stop, ms, tokens})   one per response
      -[:REQUESTED]-> (:ToolCall {id, kind, tool, server, input_json, status, ...}) one per call
      -[:TOUCHED]->   (:Ref {uid, label, title, url})       the brain_<slug> nodes a call returned
    (:Turn)-[:CITED]->(:Ref)                                 the sources of its answer

A graph cannot link into another graph, so a `Ref` stands for a brain_<slug> node by uid; it
answers "which chats touched System Auth" (`ref_threads`). ToolCall.kind is `graph` (a named
graph tool), `submit` (the answer check), `mcp` (a tool on an MCP server, through the API's MCP
connector) or `server` (an Anthropic server tool). Every node also carries `thread_id`, so a
thread reads (and deletes) in a few indexed queries. Times are epoch ms.

`Recorder` turns one run's events (`agents.ask.run_events`) into writes: `start` opens a turn,
`llm` adds a response and its calls, `step_done` stores a call's result, and the answer (or the
error) closes the turn. Writes are best effort, like traces: a failed write is logged and never
stops the answer. Only the Ask API and the CLI record; `ask`, evals and the sim never do.
Queries live in queries/chat/; `MemoryChatStore` is the test double with the same behaviour.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel
from redis.exceptions import ResponseError

from brain import db, queries
from brain.agents.loop import SUBMIT

log = logging.getLogger(__name__)

Status = Literal["running", "done", "stopped", "failed"]
Kind = Literal["graph", "submit", "mcp", "server"]
TITLE_CHARS = 80
NEVER = 2**62  # `before` for the first page of the chat list


def now_ms() -> int:
    return int(time.time() * 1000)


def _dt(ms: int | None) -> datetime | None:
    return None if ms is None else datetime.fromtimestamp(ms / 1000, UTC)


def title_of(question: str) -> str:
    line = " ".join(question.split())
    return line if len(line) <= TITLE_CHARS else line[: TITLE_CHARS - 1].rstrip() + "…"


# --- what the API returns ---------------------------------------------------------------------


class ThreadSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    turns: int
    last_status: Status


class Usage(BaseModel):
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0


class ChatLlmCall(BaseModel):
    """One Claude response: what it said and thought, with tokens and timing."""

    seq: int
    at: datetime | None = None
    model: str | None = None
    stop: str | None = None
    text: str | None = None
    thinking: str | None = None
    ms: int | None = None
    usage: Usage = Usage()


class ChatStep(BaseModel):
    """One tool call, in the Ask page's step shape plus where it came from. `call` is the seq of
    the response that asked for it; `result` is set for MCP and server calls only."""

    id: str
    call: int | None = None
    n: int | None = None
    tool: str
    kind: Kind = "graph"
    server: str | None = None
    status: str = "done"
    input: dict[str, Any] | None = None
    ms: int | None = None
    count: int | None = None
    error: str | None = None
    result: str | None = None
    rows: list[Any] = []
    nodes: list[dict[str, Any]] = []
    rels: list[dict[str, Any]] = []


class ChatTurn(BaseModel):
    n: int
    question: str
    status: Status
    started_at: datetime
    ended_at: datetime | None = None
    ms: int | None = None
    error: str | None = None
    answer: dict[str, Any] | None = None  # the `answer` event as the Ask page got it
    calls: list[ChatLlmCall] = []
    steps: list[ChatStep] = []
    rating: Literal["up", "down"] | None = None  # folded in from the trace by the API
    note: str | None = None


class Thread(BaseModel):
    """A whole chat as the Ask page reopens it."""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    last_status: Status
    turns: list[ChatTurn]


class ThreadPage(BaseModel):
    threads: list[ThreadSummary]
    next: int | None = None  # pass as `before` for the next page; None: this was the last


# --- rows -> models (shared by both stores) ---------------------------------------------------


def _loads(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except ValueError:
        return default


def summary(row: dict[str, Any]) -> ThreadSummary:
    return ThreadSummary(
        id=row["id"],
        title=row["title"] or row["id"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
        turns=row["turns"] or 0,
        last_status=row["last_status"] or "done",
    )


def assemble(
    header: dict[str, Any], turns: list[dict], calls: list[dict], steps: list[dict]
) -> Thread:
    """A thread from its rows: turns in order, each with its responses and calls in order."""
    by_turn_calls: dict[str, list[ChatLlmCall]] = {}
    for c in sorted(calls, key=lambda c: c["seq"]):
        by_turn_calls.setdefault(c["turn"], []).append(
            ChatLlmCall(
                seq=c["seq"],
                at=_dt(c.get("at")),
                model=c.get("model"),
                stop=c.get("stop"),
                text=c.get("text"),
                thinking=c.get("thinking"),
                ms=c.get("ms"),
                usage=Usage(
                    input=c.get("input_tokens") or 0,
                    output=c.get("output_tokens") or 0,
                    cache_read=c.get("cache_read") or 0,
                    cache_write=c.get("cache_write") or 0,
                ),
            )
        )
    by_turn_steps: dict[str, list[ChatStep]] = {}
    order = lambda s: (s["call"] or 0, s["kind"] == "submit", s["n"] or 0)  # noqa: E731
    for s in sorted(steps, key=order):
        by_turn_steps.setdefault(s["turn"], []).append(
            ChatStep(
                id=s["id"],
                call=s.get("call"),
                n=s.get("n"),
                tool=s["tool"],
                kind=s.get("kind") or "graph",
                server=s.get("server"),
                status=s.get("status") or "done",
                input=_loads(s.get("input_json"), {}),
                ms=s.get("ms"),
                count=s.get("count"),
                error=s.get("error"),
                result=s.get("result"),
                rows=_loads(s.get("rows_json"), []),
                nodes=_loads(s.get("nodes_json"), []),
                rels=_loads(s.get("rels_json"), []),
            )
        )
    return Thread(
        id=header["id"],
        title=header["title"] or header["id"],
        created_at=_dt(header["created_at"]),
        updated_at=_dt(header["updated_at"]),
        last_status=header["last_status"] or "done",
        turns=[
            ChatTurn(
                n=t["n"],
                question=t["question"],
                status=t["status"],
                started_at=_dt(t["started_at"]),
                ended_at=_dt(t.get("ended_at")),
                ms=t.get("ms"),
                error=t.get("error"),
                answer=_loads(t.get("answer_json"), None),
                calls=by_turn_calls.get(t["uid"], []),
                steps=by_turn_steps.get(t["uid"], []),
            )
            for t in sorted(turns, key=lambda t: t["n"])
        ],
    )


# --- stores -----------------------------------------------------------------------------------


class ChatStore(Protocol):
    """Where history goes. Writes take the params of their queries/chat/<name>.cypher."""

    def write(self, name: str, params: dict[str, Any]) -> list[dict[str, Any]]: ...
    def list_threads(self, before: int, limit: int) -> list[ThreadSummary]: ...
    def ref_threads(self, uid: str, limit: int) -> list[ThreadSummary]: ...
    def get_thread(self, thread_id: str) -> Thread | None: ...
    def delete_thread(self, thread_id: str) -> bool: ...


_SCHEMA_DONE: set[str] = set()
_SCHEMA_LOCK = threading.Lock()


class GraphChatStore:
    """The history in agent_<slug> on FalkorDB."""

    def __init__(self, slug: str):
        self.slug = slug

    def _schema(self) -> None:
        with _SCHEMA_LOCK:
            if self.slug in _SCHEMA_DONE:
                return
            g = db.agent_graph(self.slug)
            for stmt in queries.get("chat/schema").statements():
                try:
                    g.query(stmt)
                except ResponseError as e:
                    if "already indexed" not in str(e):
                        raise
            _SCHEMA_DONE.add(self.slug)

    def write(self, name: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        self._schema()
        return db.run_agent(self.slug, f"chat/{name}", params)

    def _read(self, name: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return db.run_agent(self.slug, f"chat/{name}", params, read_only=True)

    def list_threads(self, before: int, limit: int) -> list[ThreadSummary]:
        return [summary(r) for r in self._read("list_threads", {"before": before, "limit": limit})]

    def ref_threads(self, uid: str, limit: int) -> list[ThreadSummary]:
        return [summary(r) for r in self._read("ref_threads", {"uid": uid, "limit": limit})]

    def get_thread(self, thread_id: str) -> Thread | None:
        p = {"id": thread_id}
        header = self._read("get_thread", p)
        if not header:
            return None
        return assemble(
            header[0],
            self._read("thread_turns", p),
            self._read("thread_llm_calls", p),
            self._read("thread_tool_calls", p),
        )

    def delete_thread(self, thread_id: str) -> bool:
        if not self._read("get_thread", {"id": thread_id}):
            return False
        db.run_agent(self.slug, "chat/delete_thread", {"id": thread_id})
        return True

    def checkpoint_threads(self) -> list[str]:
        """Threads with checkpoints and no history (for the backfill)."""
        return [r["thread_id"] for r in self._read("checkpoint_threads", {})]


class MemoryChatStore:
    """The same writes and reads in memory, for tests (no FalkorDB)."""

    def __init__(self) -> None:
        self.threads: dict[str, dict[str, Any]] = {}
        self.turns: dict[str, dict[str, Any]] = {}
        self.calls: dict[str, dict[str, Any]] = {}
        self.steps: dict[str, dict[str, Any]] = {}
        self.refs: dict[str, dict[str, Any]] = {}
        self.links: set[tuple[str, str]] = set()  # (turn or step uid, ref uid)
        self.fail = False  # set to make every write raise (best-effort tests)

    def write(self, name: str, p: dict[str, Any]) -> list[dict[str, Any]]:
        if self.fail:
            raise ConnectionError("history store is down")
        return getattr(self, f"_{name}")(p)

    def _start_turn(self, p):
        t = self.threads.setdefault(
            p["thread_id"],
            {"id": p["thread_id"], "title": p["title"], "created_at": p["at"], "turns": 0},
        )
        t["turns"] += 1
        t.update(updated_at=p["at"], last_status="running")
        uid = f"{p['thread_id']}:{t['turns']}"
        self.turns[uid] = {"uid": uid, "thread_id": p["thread_id"], "n": t["turns"],
                           "question": p["question"], "status": "running",
                           "started_at": p["at"]}  # fmt: skip
        return [{"uid": uid, "n": t["turns"]}]

    def _add_llm_call(self, p):
        if p["turn"] not in self.turns:
            return []
        self.calls[f"{p['turn']}:{p['seq']}"] = {k: v for k, v in p.items() if k != "calls"}
        for c in p["calls"]:
            self.steps[c["uid"]] = {**self.steps.get(c["uid"], {}), **c, "turn": p["turn"],
                                    "thread_id": p["thread_id"], "call": p["seq"]}  # fmt: skip
        return [{"n": len(p["calls"])}]

    def _tool_done(self, p):
        base = self.steps.get(p["uid"]) or {k: p[k] for k in ("id", "tool", "kind", "input_json")}
        self.steps[p["uid"]] = {**base, **{k: v for k, v in p.items() if k != "refs"}}
        self.steps[p["uid"]].setdefault("call", None)
        self._link(p["uid"], p["refs"])
        return [{"n": len(p["refs"])}]

    def _finish_turn(self, p):
        turn = self.turns.get(p["turn"])
        if turn is None:
            return []
        turn.update(status=p["status"], ended_at=p["at"], ms=p["ms"], error=p["error"],
                    stop=p["stop"], model=p["model"], trace_id=p["trace_id"],
                    answer_json=p["answer_json"])  # fmt: skip
        self.threads[p["thread_id"]].update(updated_at=p["at"], last_status=p["status"])
        self._link(p["turn"], p["cited"])
        return [{"n": len(p["cited"])}]

    def _link(self, owner: str, refs: list[dict[str, Any]]) -> None:
        for r in refs:
            known = self.refs.setdefault(r["uid"], {"uid": r["uid"]})
            known.update({k: v for k, v in r.items() if v is not None})
            self.links.add((owner, r["uid"]))

    def _header(self, t: dict[str, Any]) -> dict[str, Any]:
        return {**t, "last_status": t.get("last_status")}

    def list_threads(self, before: int, limit: int) -> list[ThreadSummary]:
        rows = [t for t in self.threads.values() if t["updated_at"] < before]
        rows.sort(key=lambda t: -t["updated_at"])
        return [summary(self._header(t)) for t in rows[:limit]]

    def ref_threads(self, uid: str, limit: int) -> list[ThreadSummary]:
        owners = {o for o, r in self.links if r == uid}
        ids = {self.turns[o]["thread_id"] if o in self.turns else self.steps[o]["thread_id"]
               for o in owners}  # fmt: skip
        rows = sorted((self.threads[i] for i in ids), key=lambda t: -t["updated_at"])
        return [summary(self._header(t)) for t in rows[:limit]]

    def get_thread(self, thread_id: str) -> Thread | None:
        t = self.threads.get(thread_id)
        if t is None:
            return None

        def mine(d):
            return [v for v in d.values() if v["thread_id"] == thread_id]

        return assemble(self._header(t), mine(self.turns), mine(self.calls), mine(self.steps))

    def delete_thread(self, thread_id: str) -> bool:
        if self.threads.pop(thread_id, None) is None:
            return False
        for d in (self.turns, self.calls, self.steps):
            for k in [k for k, v in d.items() if v["thread_id"] == thread_id]:
                del d[k]
        self.links = {(o, r) for o, r in self.links if o in self.turns or o in self.steps}
        used = {r for _, r in self.links}
        self.refs = {k: v for k, v in self.refs.items() if k in used}
        return True


# --- recording a run --------------------------------------------------------------------------


def _json(value: Any) -> str:
    return json.dumps(value, default=str, separators=(",", ":"))


def _refs(uids: list[str], nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    known = {n["uid"]: n for n in nodes}
    return [
        {
            "uid": u,
            "label": known.get(u, {}).get("label"),
            "title": known.get(u, {}).get("title"),
            "url": known.get(u, {}).get("url"),
        }
        for u in uids
    ]


class Recorder:
    """Writes one run (one question) into the history as its events arrive. Never raises: a
    failed write is logged, and once the turn could not be opened the rest is skipped."""

    def __init__(self, store: ChatStore, question: str, clock=now_ms):
        self.store = store
        self.question = question
        self.clock = clock
        self.thread_id: str | None = None
        self.turn: str | None = None
        self.started = time.perf_counter()
        self.closed = False

    def _try(self, name: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            return self.store.write(name, params)
        except Exception:
            log.exception("chat history: %s failed for thread %s", name, self.thread_id)
            return []

    def on(self, event: dict[str, Any]) -> None:
        kind = event.get("kind")
        if kind == "start":
            self.thread_id = event["thread_id"]
            rows = self._try(
                "start_turn",
                {
                    "thread_id": self.thread_id,
                    "title": title_of(self.question),
                    "question": self.question,
                    "at": self.clock(),
                },
            )
            self.turn = rows[0]["uid"] if rows else None
        elif self.turn is None or self.closed:
            return
        elif kind == "llm":
            self._llm(event)
        elif kind == "step_done":
            self._step_done(event)

    def _llm(self, e: dict[str, Any]) -> None:
        usage = e.get("usage") or {}
        calls = []
        for c in e.get("calls", []):
            ran = c["kind"] in ("mcp", "server")  # finished on Anthropic's side
            calls.append({
                "uid": f"{self.turn}:{c['id']}",
                "id": c["id"],
                "tool": c["tool"],
                "kind": c["kind"],
                "server": c.get("server"),
                "input_json": _json(c.get("input") or {}),
                "status": ("failed" if c.get("error") else "done") if ran else "running",
                "error": c.get("error"),
                "result": c.get("result"),
            })  # fmt: skip
        self._try(
            "add_llm_call",
            {
                "turn": self.turn,
                "thread_id": self.thread_id,
                "seq": e["seq"],
                "at": self.clock(),
                "model": e.get("model"),
                "stop": e.get("stop"),
                "text": e.get("text"),
                "thinking": e.get("thinking"),
                "ms": e.get("ms"),
                "input_tokens": usage.get("input", 0),
                "output_tokens": usage.get("output", 0),
                "cache_read": usage.get("cache_read", 0),
                "cache_write": usage.get("cache_write", 0),
                "calls": calls,
            },
        )

    def _step_done(self, e: dict[str, Any]) -> None:
        nodes = e.get("nodes") or []
        self._try(
            "tool_done",
            {
                "turn": self.turn,
                "thread_id": self.thread_id,
                "uid": f"{self.turn}:{e['id']}",
                "id": e["id"],
                "tool": e["tool"],
                "kind": "submit" if e["tool"] == SUBMIT else "graph",
                "n": e.get("n"),
                "input_json": _json(e.get("input") or {}),
                "status": "failed" if e.get("error") else "done",
                "error": e.get("error"),
                "ms": e.get("ms"),
                "count": e.get("count"),
                "rows_json": _json(e.get("rows") or []),
                "nodes_json": _json(nodes),
                "rels_json": _json(e.get("rels") or []),
                "refs": _refs(e.get("uids") or [], nodes),
            },
        )

    def answer(
        self, payload: dict[str, Any], model: str | None = None, ms: int | None = None
    ) -> None:
        """Close the turn with the `answer` event (`ask.answer_out`) the Ask page got. `ms`
        overrides the measured duration (the backfill knows it from the trace)."""
        body = {k: v for k, v in payload.items() if k != "kind"}
        status = "stopped" if body.get("stop") == "stopped" else "done"
        cited = body.get("sources") or []
        self._close(
            status,
            error=None,
            stop=body.get("stop"),
            model=body.get("model") or model,
            trace_id=body.get("trace_id"),
            answer_json=_json(body),
            cited=[{k: s.get(k) for k in ("uid", "label", "title", "url")} for s in cited],
            ms=ms,
        )

    def fail(self, problem: str, trace_id: str | None = None, ms: int | None = None) -> None:
        self._close("failed", error=problem, stop="error", model=None, trace_id=trace_id,
                    answer_json=None, cited=[], ms=ms)  # fmt: skip

    def _close(self, status: Status, ms: int | None = None, **kw: Any) -> None:
        if self.turn is None or self.closed:
            return
        self.closed = True
        measured = round((time.perf_counter() - self.started) * 1000)
        self._try(
            "finish_turn",
            {
                "thread_id": self.thread_id,
                "turn": self.turn,
                "status": status,
                "at": self.clock(),
                "ms": measured if ms is None else ms,
                **kw,
            },
        )
