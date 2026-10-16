"""Company registry: the companies/*.yaml files as a list the API can read and write.

Why: the HTTP API and the CLI must agree on what a company is, and one broken or hand-edited file
must not hide the others. So the registry
- lists every file and reports a bad one as `InvalidCompany` instead of raising,
- validates a draft (from a form) into field paths the UI can attach to inputs, including the
  fields inside each `sources[i]` entry, which pydantic cannot reach through `list[Any]`,
- writes new files in a fixed key order and edits existing ones with a ruamel round trip, so
  comments and layout people added by hand survive,
- replaces files atomically (temp file in the same folder, then rename), so a reader never sees
  a half-written config.
"""

from __future__ import annotations

import io
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from brain import config
from brain.config import CompanyConfig

# Sections whose keys are edited one by one on update; `sources` is replaced as a whole.
_NESTED = ("window", "systems", "people")


class FieldError(BaseModel):
    loc: list[str | int]
    msg: str


class InvalidCompany(BaseModel):
    slug: str
    error: str


def _path(slug: str) -> Path:
    if not re.fullmatch(config.SLUG_RE, slug):  # also keeps "../x" out of the folder
        raise ValueError(f"invalid company slug: {slug!r}")
    return config.companies_dir() / f"{slug}.yaml"


def exists(slug: str) -> bool:
    return bool(re.fullmatch(config.SLUG_RE, slug)) and _path(slug).is_file()


def read(slug: str) -> CompanyConfig:
    return config.load_company(slug)


def describe(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
    return str(exc)


def list_companies() -> list[CompanyConfig | InvalidCompany]:
    """Every companies/*.yaml: valid ones by name, then invalid ones by slug."""
    valid: list[CompanyConfig] = []
    invalid: list[InvalidCompany] = []
    for file in config.companies_dir().glob("*.yaml"):
        try:
            valid.append(config.load_company(file.stem))
        except (OSError, yaml.YAMLError, ValueError) as exc:  # ValidationError is a ValueError
            invalid.append(InvalidCompany(slug=file.stem, error=describe(exc)))
    valid.sort(key=lambda c: (c.name.lower(), c.slug))
    invalid.sort(key=lambda c: c.slug)
    return [*valid, *invalid]


def _errors(exc: ValidationError, prefix: tuple[str | int, ...] = ()) -> list[FieldError]:
    return [FieldError(loc=[*prefix, *e["loc"]], msg=e["msg"]) for e in exc.errors()]


def validate_draft(data: dict[str, Any]) -> tuple[CompanyConfig | None, list[FieldError]]:
    """Validate an unsaved company; errors carry the full path, e.g. ["sources", 0, "repo"]."""
    from brain.adapters import REGISTRY  # late import: adapters import config

    errors: list[FieldError] = []
    entries = data.get("sources")
    per_source = isinstance(entries, list)
    if per_source:
        for i, entry in enumerate(entries):
            kind = entry.get("type") if isinstance(entry, dict) else None
            adapter = REGISTRY.get(kind)
            if adapter is None:
                known = ", ".join(sorted(REGISTRY))
                msg = f"unknown source type {kind!r} (registered: {known})"
                errors.append(FieldError(loc=["sources", i, "type"], msg=msg))
                continue
            try:
                adapter.source_model.model_validate(entry)
            except ValidationError as exc:
                errors.extend(_errors(exc, ("sources", i)))

    cfg: CompanyConfig | None = None
    try:
        cfg = CompanyConfig.model_validate(data)
    except ValidationError as exc:
        # Source entries were checked one by one above, with better paths than pydantic gives.
        errors.extend(e for e in _errors(exc) if not (per_source and e.loc[0] == "sources"))
    return (cfg if not errors else None), errors


def _dump(cfg: CompanyConfig) -> dict[str, Any]:
    data = cfg.model_dump(mode="json")  # field order: slug, name, data_permission, window, ...
    data["window"]["since"] = cfg.window.since  # a date, so YAML writes 2026-04-15 unquoted
    return data


def _yaml() -> YAML:
    yml = YAML(typ="rt")
    yml.default_flow_style = False
    yml.preserve_quotes = True
    yml.width = 4096  # never wrap long globs or repo names
    yml.indent(mapping=2, sequence=4, offset=2)  # matches companies/falkordb.yaml
    return yml


def _to_text(data: Any) -> str:
    buf = io.StringIO()
    _yaml().dump(data, buf)
    return buf.getvalue()


def render_yaml(cfg: CompanyConfig) -> str:
    return _to_text(_dump(cfg))


def _atomic_write(path: Path, text: str, *, exclusive: bool = False) -> None:
    """Write `text` to `path` via a temp file in the same folder. `exclusive` refuses to
    replace an existing file (FileExistsError), without a check-then-write race."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        if exclusive:
            os.link(tmp, path)  # fails with FileExistsError if `path` exists
        else:
            os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_new(cfg: CompanyConfig) -> Path:
    path = _path(cfg.slug)
    _atomic_write(path, render_yaml(cfg), exclusive=True)
    return path


def update(slug: str, cfg: CompanyConfig) -> None:
    """Edit companies/<slug>.yaml in place: only the keys that changed are touched, so comments
    and layout elsewhere stay. `sources` is replaced as a whole when it changed."""
    if cfg.slug != slug:
        raise ValueError(f"cannot change slug {slug!r} to {cfg.slug!r}")
    path = _path(slug)
    if not path.is_file():
        raise FileNotFoundError(f"no company config at {path}")

    doc = _yaml().load(path.read_text(encoding="utf-8"))
    try:
        current: CompanyConfig | None = config.load_company(slug)
    except (ValueError, yaml.YAMLError):
        current = None  # a broken file is being repaired: rewrite every key
    new = _dump(cfg)

    for key, value in new.items():
        if current is not None and getattr(current, key) == getattr(cfg, key):
            continue
        if key in _NESTED and isinstance(doc.get(key), CommentedMap):
            for sub, sub_value in value.items():
                if current is None or getattr(getattr(current, key), sub) != getattr(
                    getattr(cfg, key), sub
                ):
                    doc[key][sub] = sub_value
        else:
            doc[key] = value
    _atomic_write(path, _to_text(doc))
