"""Add a company from one public GitHub repository: the defaults the add-a-company dialog fills
in, and which existing company already reads a repository or its owner.

Why: the dialog asks for a repository and nothing else, so the name, slug, window and source
settings are derived here, once, for both the lookup and the create (the API calls these).
A company made this way is always `data_permission: public`; private repositories are refused
by the API before anything is written.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date

from brain import registry
from brain.config import CompanyConfig

WINDOW_MONTHS = 12  # the same default as the step-by-step form at /new
FALLBACK_SLUG = "company"


def today() -> date:
    return date.today()


def since(day: date) -> date:
    """The window start: the same day twelve months back (28 Feb for a 29 Feb)."""
    try:
        return day.replace(year=day.year - WINDOW_MONTHS // 12)
    except ValueError:
        return day.replace(year=day.year - WINDOW_MONTHS // 12, day=28)


def slug_from(text: str) -> str:
    """A GitHub login or repo name as a slug (`^[a-z0-9][a-z0-9_]*$`), or "" when nothing is
    left: lower case, every run of other characters one `_`, no `_` at either end."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def display_name(login: str, name: str | None) -> str:
    """The owner's display name, else its login in words ("acme-labs" -> "Acme Labs")."""
    if name and name.strip():
        return name.strip()
    return " ".join(w.capitalize() for w in re.split(r"[-_.]+", login) if w) or login


def candidates(repo: str) -> list[str]:
    """Slugs to try for `owner/name`, best first: the owner, the repo, both."""
    owner, name = repo.split("/", 1)
    return [slug_from(owner), slug_from(name), slug_from(f"{owner}_{name}")]


def first_free(options: list[str], taken: Callable[[str], bool]) -> str:
    """The first non-empty option that is not taken, else the first one with _2, _3, ..."""
    options = [o for o in options if o] or [FALLBACK_SLUG]
    for option in options:
        if not taken(option):
            return option
    n = 2
    while taken(f"{options[-1]}_{n}"):
        n += 1
    return f"{options[-1]}_{n}"


def company_name(repo: str, owner_name: str, slug: str) -> str:
    """The owner's name when the company is named after the owner, else owner and repo, so two
    companies of one owner are told apart in the rail."""
    owner, name = repo.split("/", 1)
    return owner_name if slug == slug_from(owner) else f"{owner_name} {name}"


def draft(repo: str, name: str, slug: str, day: date) -> dict:
    """The company config for one public repository, every kind of activity, twelve months."""
    return {
        "slug": slug,
        "name": name,
        "data_permission": "public",
        "window": {"since": since(day).isoformat()},
        "sources": [{"type": "github", "repo": repo}],
    }


def _github_repos(cfg: CompanyConfig) -> list[str]:
    return [s.repo.lower() for s in cfg.sources if s.type == "github"]


def _valid_companies() -> list[CompanyConfig]:
    return [c for c in registry.list_companies() if isinstance(c, CompanyConfig)]


def company_reading(repo: str) -> CompanyConfig | None:
    """The company that already has `owner/name` as a source (any letter case)."""
    return next((c for c in _valid_companies() if repo.lower() in _github_repos(c)), None)


def company_of_owner(owner: str) -> CompanyConfig | None:
    """A company that reads any repository of `owner`."""
    prefix = owner.lower() + "/"
    return next(
        (c for c in _valid_companies() if any(r.startswith(prefix) for r in _github_repos(c))),
        None,
    )
