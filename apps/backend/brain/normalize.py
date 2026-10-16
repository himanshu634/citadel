"""Company-specific clean-up between the adapters and the loader.

Why: adapters return what the source says; the company config says how to read it. This
module applies the config so the loader can stay dumb:
- file path -> System name (first matching rule wins, then fallback, ignore list),
- bot detection and login aliases,
- conventional-commit prefix -> Change.kind,
- the ingest window (drop activity before `window.since`),
- make sure every referenced person, team and system exists as a record.
All functions are pure: same input, same output, no network, no database.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, time
from functools import cache

from brain.canonical import (
    CanonicalRecord,
    Change,
    Comment,
    Document,
    Link,
    Ownership,
    Person,
    Review,
    System,
    Team,
    WorkItem,
    team_uid,
)
from brain.config import CompanyConfig, People, Systems

ROOT_SYSTEM = "(root)"  # fallback name for files at the top of the repo

# --- globs ------------------------------------------------------------------------------------


@cache
def _glob_regex(pattern: str) -> re.Pattern[str]:
    """Translate a path glob to a regex. `**` spans directories, `*` and `?` do not."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def glob_match(path: str, pattern: str) -> bool:
    return _glob_regex(pattern).match(path) is not None


def _clean_path(path: str) -> str:
    return path.strip().removeprefix("./").lstrip("/")


# --- path -> system ---------------------------------------------------------------------------


def system_for_path(path: str, systems: Systems) -> tuple[str, str] | None:
    """Return (system name, rule that matched) for a file path, or None if ignored.

    Order: ignore list, then rules (first match wins), then the fallback (first N folders).
    """
    path = _clean_path(path)
    if not path or any(glob_match(path, g) for g in systems.ignore):
        return None
    for rule in systems.rules:
        if glob_match(path, rule.match):
            return rule.system, rule.match
    if systems.fallback == "none":
        return None
    depth = int(systems.fallback.removeprefix("depth_"))
    folders = path.split("/")[:-1]
    if not folders:
        return ROOT_SYSTEM, f"fallback:{systems.fallback}"
    return "/".join(folders[:depth]), f"fallback:{systems.fallback}"


def systems_for_pattern(pattern: str, systems: Systems) -> list[tuple[str, str]]:
    """Map an ownership pattern (CODEOWNERS style) to systems.

    A pattern names a folder or file. It owns (a) every rule system that lives under that
    folder and (b) whatever system a file inside that folder maps to. Patterns without a
    folder prefix (`*`, `*.c`) cover the whole repo and are not mapped to single systems.
    """
    p = _clean_path(pattern)
    prefix = re.split(r"[*?\[]", p, maxsplit=1)[0]
    if not prefix:
        return []
    is_dir = p.endswith("/") or p.endswith("**") or p != prefix or "." not in prefix.split("/")[-1]
    folder = prefix.rstrip("/") + "/" if is_dir else prefix
    found: dict[str, str] = {}
    for rule in systems.rules:
        rule_prefix = re.split(r"[*?\[]", rule.match, maxsplit=1)[0]
        if rule_prefix.startswith(folder):
            found.setdefault(rule.system, rule.match)
    sample = folder + "__file__" if is_dir else folder
    if hit := system_for_path(sample, systems):
        found.setdefault(*hit)
    return list(found.items())


# --- people -----------------------------------------------------------------------------------


def canonical_login(login: str, people: People) -> str:
    return people.aliases.get(login, login)


def is_bot(login: str, people: People) -> bool:
    return login.endswith("[bot]") or login in people.bots


# --- change kind ------------------------------------------------------------------------------

_CC_RE = re.compile(r"^\s*(\w+)(?:\([^)]*\))?!?:")
_KINDS = {"feat", "fix", "perf", "ci", "build", "docs", "refactor"}
_KIND_ALIASES = {"feature": "feat", "bugfix": "fix", "doc": "docs"}


def change_kind(subject: str) -> str:
    """Parse the conventional-commit prefix: 'fix(index): crash' -> 'fix'. Else 'other'."""
    m = _CC_RE.match(subject)
    if not m:
        return "other"
    kind = m.group(1).lower()
    kind = _KIND_ALIASES.get(kind, kind)
    return kind if kind in _KINDS else "other"


# --- the pass ---------------------------------------------------------------------------------


def _in_window(dt: datetime | None, since: datetime) -> bool:
    return dt is None or dt >= since


def normalize(records: Iterable[CanonicalRecord], cfg: CompanyConfig) -> Iterator[CanonicalRecord]:
    """Apply the company config to a stream of canonical records.

    Yields the cleaned records, then any Person/Team/System that was referenced but never
    defined, so every relationship has both ends.
    """
    since = datetime.combine(cfg.window.since, time.min, tzinfo=UTC)
    people, systems = cfg.people, cfg.systems

    defined_people: set[str] = set()
    referenced_people: set[str] = set()
    defined_teams: set[str] = set()
    referenced_teams: set[str] = set()
    defined_systems: set[str] = set()
    referenced_systems: dict[str, str | None] = {}  # name -> path rule

    def login(value: str | None) -> str | None:
        if value is None:
            return None
        value = canonical_login(value, people)
        referenced_people.add(value)
        return value

    for rec in records:
        if isinstance(rec, Person):
            name = canonical_login(rec.login, people)
            defined_people.add(name)
            yield rec.model_copy(
                update={
                    "login": name,
                    "uid": Person(login=name).uid,
                    "is_bot": rec.is_bot or is_bot(name, people),
                }
            )
        elif isinstance(rec, Team):
            defined_teams.add(rec.name)
            yield rec
        elif isinstance(rec, System):
            defined_systems.add(rec.name)
            yield rec
        elif isinstance(rec, Change):
            if not _in_window(rec.changed_at(), since):
                continue
            touches: dict[str, list[str]] = {name: [] for name in rec.systems}
            for f in rec.files:
                if hit := system_for_path(f, systems):
                    touches.setdefault(hit[0], []).append(_clean_path(f))
                    referenced_systems.setdefault(hit[0], hit[1])
            for name in rec.systems:
                referenced_systems.setdefault(name, None)
            yield rec.model_copy(
                update={
                    "author_login": login(rec.author_login),
                    "kind": rec.kind or change_kind(rec.subject),
                    "touches": touches,
                }
            )
        elif isinstance(rec, WorkItem):
            if not _in_window(rec.changed_at(), since):
                continue
            yield rec.model_copy(update={"author_login": login(rec.author_login)})
        elif isinstance(rec, Review):
            if _in_window(rec.changed_at(), since):
                yield rec.model_copy(update={"reviewer_login": login(rec.reviewer_login)})
        elif isinstance(rec, Comment):
            if _in_window(rec.changed_at(), since):
                yield rec.model_copy(update={"author_login": login(rec.author_login)})
        elif isinstance(rec, Document):
            yield rec.model_copy(update={"author_login": login(rec.author_login)})
        elif isinstance(rec, Ownership):
            mapped = (
                [(s, None) for s in rec.systems]
                if rec.systems
                else systems_for_pattern(rec.pattern, systems)
            )
            for name, rule in mapped:
                referenced_systems.setdefault(name, rule)
            owner = login(rec.owner) if rec.owner_kind == "person" else rec.owner
            if rec.owner_kind == "team":
                referenced_teams.add(rec.owner)
            yield rec.model_copy(update={"owner": owner, "systems": [s for s, _ in mapped]})
        elif isinstance(rec, Link):
            if rec.to_label == "Team":
                referenced_teams.add(rec.to_uid.removeprefix("team:"))
            yield rec
        else:  # pragma: no cover - a new record type must be handled above
            raise TypeError(f"normalize does not know {type(rec).__name__}")

    for name in sorted(referenced_people - defined_people):
        yield Person(login=name, is_bot=is_bot(name, people), source="derived")
    defined_team_uids = {team_uid(t) for t in defined_teams}
    for name in sorted(referenced_teams):
        if team_uid(name) not in defined_team_uids:
            yield Team(name=name, source="derived")
    for name, rule in sorted(referenced_systems.items()):
        if name not in defined_systems:
            yield System(name=name, path_rule=rule, source="derived")
