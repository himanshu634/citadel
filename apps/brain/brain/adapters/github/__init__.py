"""GitHub source adapter: one public (or own) repository.

Why: GitHub holds most of a software company's public engineering activity. `fetch` pulls it
into a cache (GraphQL for PRs, issues, reviews, comments and commit authors; a partial git
clone for commit file lists; file texts for CODEOWNERS and docs). `records` turns that cache
into canonical records without touching the network. See fetch.py and transform.py.

Refuses private repositories unless the company's data_permission is `own`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from pydantic import field_validator

from brain.adapters.base import SourceProblem
from brain.adapters.github import client as _client
from brain.adapters.github import fetch as _fetch
from brain.adapters.github import transform as _transform
from brain.canonical import CanonicalRecord
from brain.config import CompanyConfig, SourceConfig

Part = Literal["commits", "pull_requests", "issues", "reviews", "codeowners", "repo_docs"]


class GithubSource(SourceConfig):
    type: Literal["github"]
    repo: str  # "owner/name"
    include: list[Part] = [
        "commits",
        "pull_requests",
        "issues",
        "reviews",
        "codeowners",
        "repo_docs",
    ]

    @field_validator("repo")
    @classmethod
    def _owner_slash_name(cls, v: str) -> str:
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", v):
            raise ValueError("repo must look like 'owner/name'")
        return v


class GithubAdapter:
    name = "github"
    source_model = GithubSource
    downloads = True

    def key(self, source: GithubSource) -> str:
        return f"{self.name}:{source.repo}"

    def cache_for(self, source: GithubSource, cache_dir: Path) -> Path:
        return cache_dir / source.repo.replace("/", "__")

    def fetch(self, company: CompanyConfig, source: GithubSource, cache_dir: Path) -> None:
        _fetch.run(company, source, self.cache_for(source, cache_dir))

    def check(
        self, company: CompanyConfig, source: GithubSource, cache_dir: Path
    ) -> SourceProblem | None:
        """Every build downloads first, and that needs a token. `gh auth token` is only asked
        when GITHUB_TOKEN is not set."""
        try:
            _client.token()
        except _client.GithubError:
            return SourceProblem(
                "No GitHub token: set GITHUB_TOKEN in .env or run gh auth login", blocks=True
            )
        return None

    def records(
        self, company: CompanyConfig, source: GithubSource, cache_dir: Path
    ) -> Iterator[CanonicalRecord]:
        return _transform.records(company, source, self.cache_for(source, cache_dir))
