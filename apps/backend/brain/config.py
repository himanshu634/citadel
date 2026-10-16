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
from typing import Annotated, Literal

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


class GithubSource(_Strict):
    type: Literal["github"]
    repo: str  # "owner/name"
    include: list[
        Literal["commits", "pull_requests", "issues", "reviews", "codeowners", "repo_docs"]
    ] = ["commits", "pull_requests", "issues", "reviews", "codeowners", "repo_docs"]

    @field_validator("repo")
    @classmethod
    def _owner_slash_name(cls, v: str) -> str:
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", v):
            raise ValueError("repo must look like 'owner/name'")
        return v


class LocalDocsSource(_Strict):
    type: Literal["local_docs"]
    path: Path


class CanonicalJsonlSource(_Strict):
    type: Literal["canonical_jsonl"]
    path: Path


# A new adapter adds its source model here. `type` picks the model while parsing.
Source = Annotated[
    GithubSource | LocalDocsSource | CanonicalJsonlSource, Field(discriminator="type")
]


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
    sources: list[Source]
    systems: Systems = Systems()
    people: People = People()

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
