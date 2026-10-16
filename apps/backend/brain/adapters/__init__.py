"""Adapter registry: source `type` (as written in companies/<slug>.yaml) -> adapter.

Adding a new source = one new module in this folder (adapter + its SourceConfig model) + one
line here. See _template.py.
"""

from __future__ import annotations

from brain.adapters.base import Adapter, SourceUnavailable
from brain.adapters.canonical_jsonl import CanonicalJsonlAdapter
from brain.adapters.github import GithubAdapter
from brain.adapters.local_docs import LocalDocsAdapter

REGISTRY: dict[str, Adapter] = {
    "canonical_jsonl": CanonicalJsonlAdapter(),
    "github": GithubAdapter(),
    "local_docs": LocalDocsAdapter(),
}


def get(source_type: str) -> Adapter:
    try:
        return REGISTRY[source_type]
    except KeyError:
        raise KeyError(f"no adapter registered for source type {source_type!r}") from None


__all__ = ["REGISTRY", "Adapter", "SourceUnavailable", "get"]
