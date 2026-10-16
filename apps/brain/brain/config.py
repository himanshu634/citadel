"""Settings and company config.

Why: two kinds of configuration exist and they must not mix.
- `Settings` comes from the environment (.env): where FalkorDB is, API tokens, Claude settings.
  Changing it switches local Docker <-> FalkorDB Cloud without code changes.
- `CompanyConfig` comes from `companies/<slug>.yaml`: what to ingest for one company, how
  to map file paths to systems, and which outside MCP servers the Ask agent may call. Adding a
  company means adding one of these files. Secrets never go in it: an MCP server names the env
  var that holds its token (`env_value` reads it), because the config is sent to the browser.

Relative paths inside a company YAML resolve from the repo root (the folder that holds
`companies/`), so the CLI behaves the same from the root or from apps/brain.
"""

from __future__ import annotations

import os
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def find_repo_root(start: Path | None = None) -> Path:
    """Return BRAIN_ROOT if set, else walk up from `start` (default cwd) to the companies/ dir."""
    if env_root := os.environ.get("BRAIN_ROOT"):
        return Path(env_root).resolve()
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "companies").is_dir():
            return candidate
    # Fall back to the monorepo layout: apps/brain/brain/config.py -> repo root is 3 levels up.
    return Path(__file__).resolve().parents[3]


REPO_ROOT = find_repo_root()


class Settings(BaseSettings):
    """Environment settings. Read from env vars and the repo-root .env file."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    falkordb_host: str = "localhost"
    falkordb_port: int = 6379
    falkordb_username: str | None = None
    falkordb_password: str | None = None
    falkordb_tls: bool = False  # FalkorDB Cloud offers TLS from the Startup tier up

    github_token: str | None = None
    linear_api_key: str | None = None

    embedding_dim: int = 768

    # Claude answers questions over the graph (the agents package). pydantic-settings reads .env
    # but does not export it, so agents/llm.py passes the key on; unset lets the SDK use its own
    # chain.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-5-5"  # cheap while the product takes shape
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    anthropic_max_tokens: int = 64000

    @field_validator(
        "falkordb_username",
        "falkordb_password",
        "github_token",
        "linear_api_key",
        "anthropic_api_key",
        mode="before",
    )
    @classmethod
    def _empty_is_none(cls, v: str | None) -> str | None:
        return v or None


@lru_cache
def get_settings() -> Settings:
    return Settings()


def env_value(name: str) -> str | None:
    """An env var by name, from the process or else the repo-root .env (which Settings reads but
    does not export). Empty counts as unset."""
    if value := os.environ.get(name):
        return value
    from dotenv import dotenv_values

    env_file = REPO_ROOT / ".env"
    return (dotenv_values(env_file).get(name) or None) if env_file.is_file() else None


# --- Company config -------------------------------------------------------------------------

SLUG_RE = r"^[a-z0-9][a-z0-9_]*$"  # becomes part of the graph name brain_<slug>


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Window(_Strict):
    since: date


class SourceConfig(BaseModel):
    """Base for one entry under `sources:`. Each adapter defines its own subclass (with a
    `type: Literal[...]` and its settings) next to its code, so adding a source type needs no
    change here. CompanyConfig validates every entry against the registered adapter's model."""

    model_config = ConfigDict(extra="forbid")
    type: str


class PathSource(SourceConfig):
    """A source that reads a local folder (path is repo-root relative)."""

    path: Path


class SystemRule(_Strict):
    match: str  # glob on the repo-relative path, e.g. "src/index/**"
    system: str


class Systems(_Strict):
    rules: list[SystemRule] = []
    fallback: Literal["depth_1", "depth_2", "depth_3", "none"] = "depth_2"
    ignore: list[str] = []


class People(_Strict):
    bots: list[str] = []
    aliases: dict[str, str] = {}  # "git author name" -> "login"


class McpServer(_Strict):
    """An outside MCP server the Ask agent may call through the Messages API's MCP connector
    (agents/mcp.py), e.g. a handbook or docs server. Anthropic connects to it, so it must be
    reachable over public HTTPS. Changing this list needs no rebuild."""

    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")  # also the `mcp:<name>/...` citations
    url: str = Field(pattern=r"^https://\S+$")
    token_env: str | None = Field(default=None, pattern=r"^[A-Z_][A-Z0-9_]*$")  # bearer token
    allowed_tools: list[str] | None = None  # None: every tool the server lists


class CompanyConfig(_Strict):
    slug: str = Field(pattern=SLUG_RE)
    name: str
    data_permission: Literal["public", "synthetic", "own"]
    window: Window
    sources: list[Any]  # each entry becomes its adapter's SourceConfig subclass, see below
    systems: Systems = Systems()
    people: People = People()
    mcp_servers: list[McpServer] = []

    @field_validator("mcp_servers")
    @classmethod
    def _unique_server_names(cls, servers: list[McpServer]) -> list[McpServer]:
        names = [s.name for s in servers]
        if dupes := sorted({n for n in names if names.count(n) > 1}):
            raise ValueError(f"MCP server names must be unique: {', '.join(dupes)}")
        return servers

    @field_validator("sources")
    @classmethod
    def _sources_via_registry(cls, entries: list[Any]) -> list[SourceConfig]:
        from brain.adapters import REGISTRY  # late import: adapters import this module

        out = []
        for i, entry in enumerate(entries):
            kind = entry.get("type") if isinstance(entry, dict) else None
            adapter = REGISTRY.get(kind)
            if adapter is None:
                known = ", ".join(sorted(REGISTRY))
                raise ValueError(f"sources[{i}]: unknown type {kind!r} (registered: {known})")
            out.append(adapter.source_model.model_validate(entry))
        return out

    @property
    def graph_name(self) -> str:
        return graph_name(self.slug)

    def resolve(self, path: Path) -> Path:
        """Resolve a config-relative path against the repo root."""
        return path if path.is_absolute() else REPO_ROOT / path


def graph_name(slug: str) -> str:
    """One FalkorDB graph per company: brain_<slug>. Never mix companies in one graph."""
    if not re.fullmatch(SLUG_RE, slug):
        raise ValueError(f"invalid company slug: {slug!r}")
    return f"brain_{slug}"


def companies_dir() -> Path:
    return REPO_ROOT / "companies"


def raw_dir(slug: str, adapter: str) -> Path:
    """Where an adapter caches raw API responses for a company (ingestion input, not a store)."""
    return REPO_ROOT / "data" / "raw" / slug / adapter


def load_company(slug: str) -> CompanyConfig:
    path = companies_dir() / f"{slug}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no company config at {path}; run `make init SLUG={slug}` first")
    data = yaml.safe_load(path.read_text())
    cfg = CompanyConfig.model_validate(data)
    if cfg.slug != slug:
        raise ValueError(f"{path.name} declares slug {cfg.slug!r}, expected {slug!r}")
    return cfg
