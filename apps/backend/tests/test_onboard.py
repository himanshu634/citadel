"""backend.onboard: the pure parts of adding a company from one GitHub repository."""

from __future__ import annotations

from datetime import date

import pytest
from backend import onboard
from backend.registry import validate_draft


@pytest.mark.parametrize(
    ("text", "slug"),
    [
        ("FalkorDB", "falkordb"),
        ("acme-labs", "acme_labs"),
        ("Acme--Labs__", "acme_labs"),
        ("falkordb-py", "falkordb_py"),
        ("-x-", "x"),
        ("_.", ""),
    ],
)
def test_slug_from(text, slug):
    assert onboard.slug_from(text) == slug


@pytest.mark.parametrize(
    ("login", "name", "out"),
    [
        ("FalkorDB", "FalkorDB", "FalkorDB"),
        ("torvalds", "Linus Torvalds", "Linus Torvalds"),
        ("acme-labs", None, "Acme Labs"),
        ("acme_labs", "  ", "Acme Labs"),
    ],
)
def test_display_name(login, name, out):
    assert onboard.display_name(login, name) == out


@pytest.mark.parametrize(
    ("today", "since"),
    [
        (date(2026, 10, 16), date(2025, 10, 16)),
        (date(2028, 2, 29), date(2027, 2, 28)),  # no 29 Feb a year back
    ],
)
def test_since_is_twelve_months_back(today, since):
    assert onboard.since(today) == since


def test_first_free_slug_tries_candidates_then_suffixes():
    taken = {"acme", "widgets", "acme_widgets", "acme_2"}
    options = ["acme", "widgets", "acme_widgets"]
    assert onboard.first_free(options, lambda s: s in taken) == "acme_widgets_2"
    assert onboard.first_free(["acme", "widgets"], lambda s: False) == "acme"
    assert onboard.first_free(["", "widgets"], lambda s: False) == "widgets"
    assert onboard.first_free(["", ""], lambda s: False) == "company"


def test_candidates_owner_then_repo_then_both():
    assert onboard.candidates("FalkorDB/falkordb-py") == [
        "falkordb",
        "falkordb_py",
        "falkordb_falkordb_py",
    ]


def test_draft_is_a_valid_public_github_company():
    draft = onboard.draft("acme-labs/platform", "Acme Labs", "acme_labs", date(2026, 10, 16))
    cfg, errors = validate_draft(draft)
    assert errors == [] and cfg is not None
    assert cfg.data_permission == "public"
    assert str(cfg.window.since) == "2025-10-16"
    [source] = cfg.sources
    assert source.type == "github" and source.repo == "acme-labs/platform"
    assert len(source.include) == 6  # every kind of activity
