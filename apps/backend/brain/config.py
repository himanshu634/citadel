"""Settings and company config.

Why: two kinds of configuration exist and they must not mix.
- `Settings` comes from the environment (.env): where FalkorDB is, API tokens, embedding model.
  Changing it switches local Docker <-> FalkorDB Cloud without code changes.
- `CompanyConfig` comes from `companies/<slug>.yaml`: what to ingest for one company and how
  to map file paths to systems. Adding a company means adding one of these files.

Relative paths inside a company YAML resolve from the repo root (the folder that holds
`companies/`), so the CLI behaves the same from the root or from apps/backend.
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
    # Fall back to the monorepo layout: apps/backend/brain/config.py -> repo root is 3 levels up.
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

    google_cloud_project: str | None = None
    google_cloud_location: str = "us-central1"
    embedding_model: str = "text-embedding-005"
    embedding_dim: int = 768

    @field_validator("falkordb_username", "falkordb_password", "github_token", mode="before")
    @classmethod
    def _empty_is_none(cls, v: str | None) -> str | None:
        return v or None


@lru_cache
def get_settings() -> Settings:
    return Settings()


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


class CompanyConfig(_Strict):
    slug: str = Field(pattern=SLUG_RE)
    name: str
    data_permission: Literal["public", "synthetic", "own"]
    window: Window
    sources: list[Any]  # each entry becomes its adapter's SourceConfig subclass, see below
    systems: Systems = Systems()
    people: People = People()

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
