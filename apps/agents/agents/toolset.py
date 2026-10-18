"""The graph tools as Claude sees them.

Why: the agent must not care where a tool's Cypher lives. `brain.tools` owns the named read
queries (one pydantic params model and one row model per tool); this module turns that registry
into Anthropic tool definitions, runs a call with input validation, and remembers every node a
result mentions so the answer can only cite things the graph actually returned.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

MAX_RESULT_CHARS = 40_000  # a tool result bigger than this is cut, so one call can't flood context


class GraphTool(Protocol):
    name: str
    description: str
    params: type[BaseModel]


Runner = Callable[..., list[BaseModel]]  # (slug, name, **params) -> rows, like brain.tools.call


@dataclass(frozen=True)
class ToolOutcome:
    content: str  # JSON text for the tool_result block
    is_error: bool
    seen: dict[str, dict[str, Any]]  # uid -> {uid, label, title, url} for every node in the rows
    # What the call ran with and returned, before `content` is cut to size: the Ask page draws
    # its step from these (agents.walk), never by parsing `content` back.
    params: dict[str, Any] = field(default_factory=dict)
    rows: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class Toolset:
    tools: Mapping[str, GraphTool]
    run: Runner

    def definitions(self) -> list[dict[str, Any]]:
        """Anthropic tool definitions, sorted by name so the request prefix stays cacheable."""
        return [_definition(self.tools[name]) for name in sorted(self.tools)]

    def call(self, slug: str, name: str, raw_input: Any) -> ToolOutcome:
        tool = self.tools.get(name)
        if tool is None:
            return _error(f"unknown tool {name!r}; available: {', '.join(sorted(self.tools))}")
        try:
            params = tool.params.model_validate(raw_input)
        except ValidationError as e:
            return _error(f"invalid input for {name}: {e.errors(include_url=False)}")
        try:
            rows = self.run(slug, name, **params.model_dump())
        except Exception as e:  # a failing query is reported to the model, not raised
            return _error(f"{name} failed: {type(e).__name__}: {e}")
        data = [
            r.model_dump(mode="json", by_alias=True) if isinstance(r, BaseModel) else r
            for r in rows
        ]
        seen: dict[str, dict[str, Any]] = {}
        _collect_nodes(data, seen)
        text = json.dumps({"rows": data, "count": len(data)}, default=str, ensure_ascii=False)
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + ' ... [cut: ask for fewer rows with "limit"]'
        return ToolOutcome(
            content=text, is_error=False, seen=seen, params=params.model_dump(), rows=data
        )


def graph_toolset() -> Toolset:
    """The real tools from `brain.tools` (named Cypher under queries/tools/)."""
    from brain import tools

    return Toolset(tools=tools.TOOLS, run=tools.call)


def ask_toolset() -> Toolset:
    """What Ask uses: the graph tools, the interview tools and `ask_archivist`, on the real
    ledger."""
    return with_archivist(with_interview(graph_toolset()))


def with_interview(
    base: Toolset, ledger: Callable[[str], Any] | None = None, brain: Any = None
) -> Toolset:
    """`base` plus the interview tools (`keeper/interview.py`), which read the Keeper's gaps
    and file a person's reply for a lead. `ledger(slug)` gives the keeper_<slug> store
    (default: FalkorDB); tests pass a `MemoryKeeperStore` and a fake brain."""
    from agents.keeper import interview

    extra, run_extra = interview.ask_tools(ledger or interview.keeper_ledger, brain)

    def run(slug: str, name: str, **params: Any) -> list[BaseModel]:
        if name in extra:
            return run_extra(slug, name, **params)
        return base.run(slug, name, **params)

    return Toolset(tools={**base.tools, **extra}, run=run)


def with_archivist(
    base: Toolset,
    ledger: Callable[[str], Any] | None = None,
    client: Callable[[], Any] | None = None,
    **hooks: Any,
) -> Toolset:
    """`base` plus `ask_archivist` (`archivist/live.py`), which runs the Archivist's job inline
    and forwards its steps to Ask's stream. `ledger(slug)` gives the keeper_<slug> store
    (default: FalkorDB); `client()` makes the Archivist's client when a call runs (default:
    Claude); `hooks` go to `live.run` (tests pass `clock` and `poll`). Only a call inside a
    running Ask graph streams its steps (outside one there is nowhere to send them)."""
    from agents.archivist import live
    from agents.keeper.interview import keeper_ledger
    from agents.loop import CURRENT_STEP

    def default_client() -> Any:
        from agents import llm

        return llm.client()

    def run(slug: str, name: str, **params: Any) -> list[Any]:
        if name != live.NAME:
            return base.run(slug, name, **params)
        from agents.ask import ASK_STOP

        writer, thread = _ask_run()
        return live.run(
            slug, live.AskArchivistParams(**params), client=client or default_client,
            ledger=(ledger or keeper_ledger)(slug), writer=writer, stop=ASK_STOP.get(),
            parent=CURRENT_STEP.get(), thread=thread, **hooks,
        )  # fmt: skip

    return Toolset(tools={**base.tools, **live.TOOLS}, run=run)


def _ask_run() -> tuple[Callable[[dict[str, Any]], None], str | None]:
    """The running Ask graph's stream writer and thread id (a no-op writer and None outside
    one)."""
    from langgraph.config import get_config, get_stream_writer

    try:
        writer = get_stream_writer()
        thread = get_config().get("configurable", {}).get("thread_id")
    except RuntimeError:
        return (lambda chunk: None), None
    return writer, thread


def _definition(tool: GraphTool) -> dict[str, Any]:
    schema = tool.params.model_json_schema()
    schema.pop("title", None)
    return {"name": tool.name, "description": tool.description, "input_schema": schema}


def _error(message: str) -> ToolOutcome:
    return ToolOutcome(content=json.dumps({"error": message}), is_error=True, seen={})


_TITLE_KEYS = ("title", "subject", "name", "display_name", "login", "system")


def _collect_nodes(value: Any, seen: dict[str, dict[str, Any]]) -> None:
    """Record every dict that names a node (rows and nested lists alike): by its `uid`, or by
    its first `*_uid` key when it has no `uid` (the row's subject, e.g. an expert row's
    `person_uid`). Other `*_uid`
    and `uids` values are recorded bare. Citations are checked against this, and shown with
    the title and url found here. A node a row marks `archived: true` (an Archivist find, an
    archived item's entity) keeps `archived`: its own date, "" when it has none."""
    if isinstance(value, list):
        for v in value:
            _collect_nodes(v, seen)
        return
    if not isinstance(value, dict):
        return
    uid = value.get("uid")
    if uid is None:
        uid = next((v for k, v in value.items() if k.endswith("_uid")), None)
    if isinstance(uid, str) and uid:
        node = seen.setdefault(uid, {"uid": uid})
        title = next((value[k] for k in _TITLE_KEYS if isinstance(value.get(k), str)), None)
        for key, v in (("title", title), ("url", value.get("url")), ("label", value.get("label"))):
            if v and not node.get(key):
                node[key] = v
        if value.get("archived") is True and "archived" not in node:
            node["archived"] = str(value.get("date") or "")  # an Archivist find: its own date
    for key, v in value.items():
        if key.endswith("_uid") and isinstance(v, str) and v:
            seen.setdefault(v, {"uid": v})
        elif key.endswith("uids") and isinstance(v, list):
            for u in v:
                if isinstance(u, str) and u:
                    seen.setdefault(u, {"uid": u})
        else:
            _collect_nodes(v, seen)
