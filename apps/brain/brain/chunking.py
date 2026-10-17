"""Split text into chunks and fingerprint it.

Why: semantic search embeds short passages, not whole PR bodies or documents. The embedding
model reads only the start of a text (bge: 512 tokens, about 2000 characters of English) and
ignores the rest, so text past that would never be found. The loader cuts each work-item body,
document and comment with `split_text` and writes each piece as a `Chunk`; this module decides
where long text is cut and gives each text a hash, so the embed stage can tell which chunks
changed. Pure: no database, no model.
"""

from __future__ import annotations

import hashlib

# About 300 tokens of English prose, well inside bge's 512. Code, URLs and non-English text
# take more tokens per character, so a piece of those can still be cut short by the model.
MAX_CHARS = 1200


def text_hash(text: str) -> str:
    """First 16 hex chars of the sha256 of the UTF-8 text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _hard_split(paragraph: str, max_chars: int) -> list[str]:
    """Cut one over-long paragraph at the last space before the limit (or at the limit)."""
    parts: list[str] = []
    rest = paragraph
    while len(rest) > max_chars:
        cut = rest.rfind(" ", 0, max_chars + 1)
        if cut <= 0:
            cut = max_chars
        parts.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    parts.append(rest)
    return [p for p in parts if p]


def split_text(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Split on blank lines and pack the paragraphs into pieces of at most `max_chars`.

    A paragraph longer than `max_chars` is cut at the last space before the limit. Pieces are
    stripped; empty ones are dropped, so blank text gives an empty list.
    """
    pieces: list[str] = []
    current = ""
    for paragraph in (p.strip() for p in text.split("\n\n")):
        if not paragraph:
            continue
        if current and len(current) + 2 + len(paragraph) <= max_chars:
            current = f"{current}\n\n{paragraph}"
            continue
        if current:
            pieces.append(current)
        if len(paragraph) > max_chars:
            *whole, current = _hard_split(paragraph, max_chars)
            pieces.extend(whole)
        else:
            current = paragraph
    if current:
        pieces.append(current)
    return pieces
