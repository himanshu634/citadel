"""GitHub adapter transform, from recorded (trimmed) API pages in tests/fixtures/github/.

No network: the fixtures are a cache directory exactly as `fetch` writes it.
"""

import json
import shutil
from pathlib import Path

import pytest
from brain.adapters.github import codeowners
from brain.adapters.github.transform import actor_login, records
from brain.canonical import Change, Comment, Document, Link, Ownership, Review, WorkItem
from brain.config import CompanyConfig
from brain.normalize import normalize
from pydantic import ValidationError

FIXTURE = Path(__file__).parent / "fixtures" / "github" / "FalkorDB__FalkorDB"
REPO = "github:FalkorDB/FalkorDB"
PR, ISSUE, BOT_PR, OLD_ISSUE = 3063, 2539, 3344, 8


@pytest.fixture
def company() -> CompanyConfig:
    """Fixed rules, so tuning companies/falkordb.yaml never breaks these tests."""
    return CompanyConfig.model_validate(
        {
            "slug": "gh_test",
            "name": "GH test",
            "data_permission": "public",
            "window": {"since": "2026-04-15"},
            "sources": [{"type": "github", "repo": "FalkorDB/FalkorDB"}],
            "systems": {
                "rules": [{"match": ".github/workflows/**", "system": "CI"}],
                "fallback": "depth_2",
                "ignore": ["build/graphblas/**"],
            },
            "people": {"bots": ["Copilot"]},
        }
    )


@pytest.fixture
def out(company):
    recs = list(records(company, company.sources[0], FIXTURE))
    return {r.uid: r for r in recs}, recs


def links(recs, rel):
    return {(r.from_uid, r.to_uid) for r in recs if isinstance(r, Link) and r.rel == rel}


def test_private_repo_refused_without_own(company, tmp_path):
    cache = tmp_path / "cache"
    shutil.copytree(FIXTURE, cache)
    meta = json.loads((cache / "meta.json").read_text())
    (cache / "meta.json").write_text(json.dumps({**meta, "isPrivate": True}))

    with pytest.raises(PermissionError, match="private"):
        list(records(company, company.sources[0], cache))

    own = company.model_copy(update={"data_permission": "own"})
    assert list(records(own, own.sources[0], cache))  # allowed for your own data


def test_config_rejects_bad_permission_and_unknown_source(company):
    data = company.model_dump(mode="json")
    with pytest.raises(ValidationError):
        CompanyConfig.model_validate({**data, "data_permission": "private"})
    with pytest.raises(ValidationError, match="unknown type"):
        CompanyConfig.model_validate({**data, "sources": [{"type": "jira", "url": "x"}]})


def test_pull_request_issue_reviews_comments(out):
    by_uid, recs = out
    pr = by_uid[f"{REPO}:pr:{PR}"]
    assert isinstance(pr, WorkItem) and pr.kind == "pull_request" and pr.state == "merged"
    assert by_uid[f"{REPO}:issue:{ISSUE}"].kind == "issue"
    assert (pr.uid, f"{REPO}:issue:{ISSUE}") in links(recs, "CLOSES")
    assert any(isinstance(r, Review) and r.work_item_uid == pr.uid for r in recs)
    assert any(isinstance(r, Comment) and r.work_item_uid == pr.uid for r in recs)


def test_bot_actor_gets_bot_suffix(out):
    by_uid, _ = out
    assert by_uid[f"{REPO}:pr:{BOT_PR}"].author_login == "dependabot[bot]"
    assert actor_login({"login": "Copilot", "__typename": "Bot"}) == "Copilot[bot]"
    assert actor_login(None) is None


def test_commits_get_login_from_history_and_link_to_pr(out):
    by_uid, recs = out
    changes = [r for r in recs if isinstance(r, Change)]
    assert changes and all(c.author_login == "AviAvni" for c in changes)
    part_of = links(recs, "PART_OF")
    assert any(to == f"{REPO}:pr:{PR}" for _, to in part_of)  # via the PR's merge commit


def test_codeowners_maps_patterns_to_systems_and_skips_emails_and_catch_all(out):
    _, recs = out
    owns = [r for r in recs if isinstance(r, Ownership)]
    assert all(r.pattern.strip("/") != "*" for r in owns)  # catch-all default owner skipped
    assert all("@" not in r.owner for r in owns)  # email owner skipped
    core = {s for r in owns if r.owner == "falkordb-core" for s in r.systems}
    assert "CI" in core  # /.github/ covers .github/workflows/** -> CI rule
    assert any(r.owner == "someone" and r.systems == ["CI"] for r in owns)


def test_docs_and_mentions(out):
    by_uid, recs = out
    doc = by_uid[f"{REPO}:doc:README.md"]
    assert isinstance(doc, Document) and doc.title == "FalkorDB"
    mentions = links(recs, "MENTIONS")
    assert (doc.uid, f"{REPO}:pr:{PR}") in mentions
    assert (doc.uid, "system:CI") in mentions


def test_normalized_output_drops_bulk_touched_issue_and_scrubs_email(company, out):
    _, recs = out
    norm = {r.uid: r for r in normalize(recs, company)}
    assert f"{REPO}:issue:{OLD_ISSUE}" not in norm  # only a bulk updatedAt bump in window
    assert "[email]" in norm[f"{REPO}:doc:README.md"].body
    assert norm["person:dependabot[bot]"].is_bot


@pytest.mark.parametrize(
    ("pattern", "path", "hit"),
    [
        ("/build/", "build/runtime/x.c", True),
        ("/build/", "src/build/x.c", False),
        ("docs/", "docs/a.md", True),
        ("*.md", "src/deep/README.md", True),
        ("/src/index", "src/index/a.c", True),  # no trailing slash: file or directory
        ("/CODEOWNERS", "CODEOWNERS", True),
    ],
)
def test_codeowners_pattern_matching(pattern, path, hit):
    assert bool(codeowners.matching_files(pattern, [path])) is hit
