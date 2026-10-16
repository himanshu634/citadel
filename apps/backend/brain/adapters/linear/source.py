"""Config for one `linear` entry under `sources:` in a company YAML.

Why: kept apart from the adapter so fetch and transform can import it without a cycle (the
package `__init__` imports both of them).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from brain.config import SourceConfig

TeamKey = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9]{0,6}$")]  # Linear team key, e.g. "ENG"


class LinearSource(SourceConfig):
    type: Literal["linear"]
    workspace: str = Field(pattern=r"^[a-z0-9-]+$")  # the urlKey: linear.app/<workspace>
    teams: list[TeamKey] = []  # team keys to ingest; empty means every team the key can see
