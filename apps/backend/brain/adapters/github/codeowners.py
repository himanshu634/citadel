"""Parse a CODEOWNERS file into (pattern, owner_kind, owner) rows.

Why: CODEOWNERS is the declared ownership of code areas. `@org/team` owners become Teams,
`@login` owners become people, and email owners are skipped (we never store emails).
Every line is kept: the graph shows all declared owners, not only GitHub's "last match wins".
Patterns are matched against the real file tree (gitignore rules, like GitHub does), so a
pattern maps to exactly the systems whose files it covers.
"""

from __future__ import annotations

from typing import Literal

from brain.normalize import glob_match

Owner = tuple[str, Literal["person", "team"], str]  # (pattern, owner_kind, owner)


def parse(text: str) -> list[Owner]:
    rows: list[Owner] = []
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].strip()  # drop inline comments
        if not line or line.startswith("#"):
            continue
        pattern, *owners = line.split()
        for owner in owners:
            if not owner.startswith("@"):
                continue  # an email address (or junk): never stored
            handle = owner[1:]
            if "/" in handle:
                rows.append((pattern, "team", handle.split("/", 1)[1]))
            else:
                rows.append((pattern, "person", handle))
    return rows


def to_glob(pattern: str) -> str:
    """CODEOWNERS (gitignore-style) pattern -> our path glob.

    A slash at the start or in the middle anchors the pattern to the repo root; otherwise it
    matches at any depth. A trailing slash means "this directory and everything in it".
    """
    p = pattern
    anchored = "/" in p.rstrip("/")
    p = p.strip("/") if p.endswith("/") else p.lstrip("/")
    if pattern.endswith("/"):
        p += "/**"
    return p if anchored else "**/" + p


def matching_files(pattern: str, files: list[str]) -> list[str]:
    """Files covered by a pattern. A name without a trailing slash may also be a directory."""
    g = to_glob(pattern)
    return [f for f in files if glob_match(f, g) or glob_match(f, g + "/**")]


def is_catch_all(pattern: str) -> bool:
    """`*` / `/**` style default-owner lines: they say nothing about one area."""
    return pattern.strip("/") in {"*", "**", "**/*"}
