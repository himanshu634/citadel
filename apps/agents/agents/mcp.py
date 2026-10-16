"""Outside sources: a company's MCP servers, called through the Messages API's MCP connector.

Why: some answers need more than the graph (a handbook, a docs site). Anthropic connects to
each server in `companies/<slug>.yaml` `mcp_servers:` and runs its tools inside the Claude call,
so the loop has nothing to execute: MCP calls come back as `mcp_tool_use` + `mcp_tool_result`
blocks in the assistant content, next to the graph tools' `tool_use`. This module turns the
config into the request's parts:
- `mcp_servers` (url, name, bearer token read from the env var the config names),
- one `mcp_toolset` per server in `tools` (an allowlist turns the rest off), after the graph
  tools and sorted by server name, so the tool list is static per company and stays cacheable,
- the beta header. `mcp-client-2026-09-15` (not 2025-11-20) records each server's tool list in
  an `mcp_tool_listing` block of the response; replayed with the thread, it pins that list, so
  a server that changes its tools mid-thread changes neither the cached prefix nor the tool set
  Claude saw. The header goes on every request whose history holds an `mcp_*` block.

Citations: an MCP result has no graph uid, so a successful call is recorded in `seen` as
`mcp:<server>/<tool>` (label `MCP`); the answer may cite that uid like a node. Failed calls are
not citable. Limits: an unreachable server fails the whole Claude call (the API reports it), and
there is no retry without MCP, because dropping the toolsets would change the thread's tools.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from brain.config import McpServer, env_value

BETA = "mcp-client-2026-09-15"
LABEL = "MCP"  # the `label` of an MCP source in `seen` and in answers
_BLOCKS = ("mcp_tool_use", "mcp_tool_result", "mcp_tool_listing")


class McpTokenMissing(RuntimeError):
    """A configured server's token env var is unset. The question fails with this sentence
    rather than silently answering without a source someone configured."""


@dataclass(frozen=True)
class Connector:
    servers: tuple[dict[str, Any], ...]  # the request's `mcp_servers` (tokens included)
    toolsets: tuple[dict[str, Any], ...]  # one `mcp_toolset` per server, for `tools`

    @classmethod
    def from_config(cls, servers: Sequence[McpServer]) -> Connector | None:
        """The connector for a company's servers, or None when it has none. Raises
        McpTokenMissing when a server's token env var is unset."""
        if not servers:
            return None
        ordered = sorted(servers, key=lambda s: s.name)
        return cls(
            servers=tuple(_server(s) for s in ordered),
            toolsets=tuple(_toolset(s) for s in ordered),
        )


def _server(s: McpServer) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "url", "url": s.url, "name": s.name}
    if s.token_env:
        token = env_value(s.token_env)
        if not token:
            raise McpTokenMissing(
                f"MCP server {s.name!r} needs a token: set {s.token_env} in .env or the "
                "environment, or remove token_env from the company's mcp_servers."
            )
        out["authorization_token"] = token
    return out


def _toolset(s: McpServer) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "mcp_toolset", "mcp_server_name": s.name}
    if s.allowed_tools is not None:
        out["default_config"] = {"enabled": False}
        out["configs"] = {t: {"enabled": True} for t in sorted(set(s.allowed_tools))}
    return out


def request_params(
    connector: Connector | None, messages: Iterable[dict[str, Any]], betas: Sequence[str]
) -> dict[str, Any]:
    """`mcp_servers` and `betas` for one Claude call: the given betas, plus the MCP header when
    the company has servers or the thread already holds MCP blocks (a server removed from the
    config). Empty when neither applies, so a company without MCP sends what it did before."""
    out: dict[str, Any] = {}
    if connector is not None:
        out["mcp_servers"] = list(connector.servers)
    if connector is not None or _has_mcp_blocks(messages):
        betas = [*betas, BETA]
    if betas:
        out["betas"] = list(betas)
    return out


def _has_mcp_blocks(messages: Iterable[dict[str, Any]]) -> bool:
    return any(
        isinstance(m.get("content"), list)
        and any(b.get("type") in _BLOCKS for b in m["content"] if isinstance(b, dict))
        for m in messages
    )


def uid(server: str, tool: str) -> str:
    """How an answer cites what a tool on an MCP server returned."""
    return f"mcp:{server}/{tool}"


def seen_from(content: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The citable MCP results in one response: a `seen` entry per successful call."""
    ok = {
        b["tool_use_id"]
        for b in content
        if b["type"] == "mcp_tool_result" and not b.get("is_error")
    }
    out: dict[str, dict[str, Any]] = {}
    for b in content:
        if b["type"] == "mcp_tool_use" and b["id"] in ok:
            key = uid(b["server_name"], b["name"])
            out[key] = {"uid": key, "label": LABEL, "title": f"{b['name']} on {b['server_name']}"}
    return out
