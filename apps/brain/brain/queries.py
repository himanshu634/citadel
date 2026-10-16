"""Load named Cypher queries from apps/brain/queries/.

Why: every query the product depends on lives in a .cypher file with a header comment
(purpose, params, returns). Python never holds Cypher strings; it asks for a query by name,
e.g. `get("tools/experts_for_system")`. That keeps the queries reviewable in one place.

File format:
    // purpose / params / returns / example   <- header: leading `//` lines
    MATCH ...                                  <- body
A file may hold several statements separated by `;` on its own line end (used by schema files,
because FalkorDB runs one statement per GRAPH.QUERY).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

QUERIES_DIR = Path(__file__).resolve().parent.parent / "queries"


@dataclass(frozen=True)
class NamedQuery:
    name: str  # e.g. "schema/indexes"
    header: str  # the leading comment block, without the `//`
    body: str  # everything after the header

    def statements(self) -> list[str]:
        """Split the body into single statements (on `;`), dropping comments and blanks."""
        lines = [ln for ln in self.body.splitlines() if not ln.strip().startswith("//")]
        parts = "\n".join(lines).split(";")
        return [p.strip() for p in parts if p.strip()]


def _parse(name: str, text: str) -> NamedQuery:
    lines = text.splitlines()
    header: list[str] = []
    i = 0
    while i < len(lines) and (lines[i].startswith("//") or not lines[i].strip()):
        header.append(lines[i].removeprefix("//").removeprefix(" "))
        i += 1
    return NamedQuery(
        name=name, header="\n".join(header).strip(), body="\n".join(lines[i:]).strip()
    )


@cache
def get(name: str) -> NamedQuery:
    path = QUERIES_DIR / f"{name}.cypher"
    if not path.exists():
        raise KeyError(f"no query named {name!r} (looked for {path})")
    return _parse(name, path.read_text())


def list_names(folder: str) -> list[str]:
    """All query names in a folder, e.g. list_names("tools") -> ["tools/graph_stats", ...]."""
    return sorted(f"{folder}/{p.stem}" for p in (QUERIES_DIR / folder).glob("*.cypher"))
