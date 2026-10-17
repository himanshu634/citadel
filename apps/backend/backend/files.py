"""File writes the backend shares (the registry's YAML, the job runner's snapshots)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write(
    path: Path, text: str, *, exclusive: bool = False, mode: int | None = None
) -> None:
    """Write `text` to `path` via a temp file in the same folder, so a reader never sees a
    half-written file. `exclusive` refuses to replace an existing file (FileExistsError),
    without a check-then-write race. `mode` sets the file's permissions (mkstemp makes 0600)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        if mode is not None:
            os.chmod(tmp, mode)
        if exclusive:
            os.link(tmp, path)  # fails with FileExistsError if `path` exists
        else:
            os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
