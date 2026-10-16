"""Add a company from one public GitHub repository: GET/POST /api/onboard/github/..."""

from __future__ import annotations

from datetime import date

import httpx
import pytest
from brain import onboard, registry
from brain.adapters.github.client import GithubError, GithubRateLimited
from brain.api import checks
from brain.config import CompanyConfig

from .conftest import write
from .test_checks import FakeClient, use


def repo(name_with_owner="acme-labs/platform", private=False, owner_name="Acme Labs"):
    login = name_with_owner.split("/")[0]
    return {
        "repository": {
            "nameWithOwner": name_with_owner,
            "isPrivate": private,
            "owner": {"login": login, "name": owner_name},
        }
    }


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(onboard, "today", lambda: date(2026, 10, 16))


def company(slug, name, gh_repo):
    registry.write_new(
        CompanyConfig.model_validate(onboard.draft(gh_repo, name, slug, date(2026, 10, 16)))
    )


# --- lookup ------------------------------------------------------------------------------------


def test_lookup_public_repo_suggests_owner_name_and_slug(client, api_root, monkeypatch):
    fake = use(monkeypatch, FakeClient(repo()))
    r = client.get("/api/onboard/github/acme-labs/platform")
    assert r.status_code == 200
    assert r.json() == {
        "repo": "acme-labs/platform",
        "exists": True,
        "private": False,
        "owner_name": "Acme Labs",
        "name": "Acme Labs",
        "slug": "acme_labs",
        "since": "2025-10-16",
        "company": None,
        "owner_company": None,
    }
    assert fake.calls == [("repo_owner", {"owner": "acme-labs", "name": "platform"})]
    assert fake.closed


def test_lookup_uses_github_spelling(client, api_root, monkeypatch):
    use(monkeypatch, FakeClient(repo("Acme-Labs/Platform")))
    assert client.get("/api/onboard/github/acme-labs/platform").json()["repo"] == (
        "Acme-Labs/Platform"
    )


def test_lookup_owner_without_display_name(client, api_root, monkeypatch):
    use(monkeypatch, FakeClient(repo(owner_name=None)))
    body = client.get("/api/onboard/github/acme-labs/platform").json()
    assert body["owner_name"] == "Acme Labs" and body["name"] == "Acme Labs"


def test_lookup_not_found(client, api_root, monkeypatch):
    use(monkeypatch, FakeClient({"repository": None}))
    body = client.get("/api/onboard/github/acme-labs/platfrom").json()
    assert body["exists"] is False and body["slug"] is None and body["name"] is None


def test_lookup_graphql_not_found_error(client, api_root, monkeypatch):
    use(monkeypatch, FakeClient(error=GithubError("GraphQL errors: [{'type': 'NOT_FOUND'}]")))
    assert client.get("/api/onboard/github/acme/nope").json()["exists"] is False


def test_lookup_private_repo_is_reported_without_a_suggestion(client, api_root, monkeypatch):
    use(monkeypatch, FakeClient(repo("acme-labs/billing", private=True)))
    body = client.get("/api/onboard/github/acme-labs/billing").json()
    assert body["exists"] is True and body["private"] is True and body["slug"] is None


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (GithubRateLimited("slow down"), 429),
        (GithubError("GitHub API 401: Bad credentials"), 502),
        (httpx.ConnectTimeout("slow"), 502),
    ],
)
def test_lookup_github_failures_match_the_checks_route(client, monkeypatch, error, status):
    use(monkeypatch, FakeClient(error=error))
    assert client.get("/api/onboard/github/acme/widgets").status_code == status


def test_lookup_without_token_is_424(client, monkeypatch):
    def no_token():
        raise GithubError("no token")

    monkeypatch.setattr(checks, "github_client", no_token)
    r = client.get("/api/onboard/github/acme/widgets")
    assert r.status_code == 424 and "GITHUB_TOKEN" in r.json()["detail"]


def test_lookup_bad_owner_is_422(client):
    assert client.get("/api/onboard/github/-acme/widgets").status_code == 422


def test_lookup_repo_already_read_by_a_company(client, api_root, monkeypatch):
    company("falkordb", "FalkorDB", "FalkorDB/FalkorDB")
    use(monkeypatch, FakeClient(repo("FalkorDB/FalkorDB", owner_name="FalkorDB")))
    body = client.get("/api/onboard/github/falkordb/falkordb").json()
    assert body["company"] == {"slug": "falkordb", "name": "FalkorDB"}


def test_lookup_owner_has_a_company_suggests_a_separate_slug(client, api_root, monkeypatch):
    company("falkordb", "FalkorDB", "FalkorDB/FalkorDB")
    use(monkeypatch, FakeClient(repo("FalkorDB/falkordb-py", owner_name="FalkorDB")))
    body = client.get("/api/onboard/github/FalkorDB/falkordb-py").json()
    assert body["company"] is None
    assert body["owner_company"] == {"slug": "falkordb", "name": "FalkorDB"}
    assert body["slug"] == "falkordb_py"
    assert body["name"] == "FalkorDB falkordb-py"


def test_lookup_slug_left_behind_is_skipped(client, api_root, monkeypatch):
    monkeypatch.setattr(
        "brain.db.company_graphs", lambda slug: ["x"] if slug == "acme_labs" else []
    )
    use(monkeypatch, FakeClient(repo()))
    assert client.get("/api/onboard/github/acme-labs/platform").json()["slug"] == "platform"


# --- create and start --------------------------------------------------------------------------


def test_create_writes_public_company_and_starts_its_build(client, api_root, monkeypatch, gate):
    use(monkeypatch, FakeClient(repo()))
    r = client.post("/api/onboard/github", json={"repo": "acme-labs/platform"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["company"]["slug"] == "acme_labs" and body["company"]["name"] == "Acme Labs"
    assert body["company"]["data_permission"] == "public"
    assert body["build"]["slug"] == "acme_labs" and body["build"]["state"] in ("queued", "running")
    assert body["build_error"] is None
    cfg = registry.read("acme_labs")
    assert cfg.sources[0].repo == "acme-labs/platform"
    assert str(cfg.window.since) == "2025-10-16"


def test_create_takes_name_and_slug(client, api_root, monkeypatch, gate):
    use(monkeypatch, FakeClient(repo()))
    body = {"repo": "acme-labs/platform", "name": "Acme", "slug": "acme"}
    r = client.post("/api/onboard/github", json=body)
    assert r.status_code == 201 and r.json()["company"]["name"] == "Acme"
    assert registry.exists("acme")


def test_create_refuses_private_repo(client, api_root, monkeypatch):
    use(monkeypatch, FakeClient(repo("acme-labs/billing", private=True)))
    r = client.post("/api/onboard/github", json={"repo": "acme-labs/billing"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "private_repo"
    assert not registry.exists("acme_labs")


def test_create_refuses_missing_repo(client, api_root, monkeypatch):
    use(monkeypatch, FakeClient({"repository": None}))
    r = client.post("/api/onboard/github", json={"repo": "acme-labs/platfrom"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "not_found"


def test_create_refuses_repo_a_company_already_reads(client, api_root, monkeypatch):
    company("falkordb", "FalkorDB", "FalkorDB/FalkorDB")
    use(monkeypatch, FakeClient(repo("FalkorDB/FalkorDB", owner_name="FalkorDB")))
    r = client.post("/api/onboard/github", json={"repo": "FalkorDB/FalkorDB", "slug": "other"})
    assert r.status_code == 409
    assert r.json()["detail"] == {"code": "repo_taken", "slug": "falkordb", "name": "FalkorDB"}


def test_create_given_slug_taken_is_409(client, api_root, monkeypatch):
    write(api_root, "acme_labs", name="Acme Labs")
    use(monkeypatch, FakeClient(repo()))
    r = client.post("/api/onboard/github", json={"repo": "acme-labs/platform", "slug": "acme_labs"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "slug_taken"


def test_create_without_slug_picks_a_free_one(client, api_root, monkeypatch, gate):
    write(api_root, "acme_labs", name="Acme Labs")
    use(monkeypatch, FakeClient(repo()))
    r = client.post("/api/onboard/github", json={"repo": "acme-labs/platform"})
    assert r.status_code == 201 and r.json()["company"]["slug"] == "platform"


def test_create_bad_slug_is_field_error(client, api_root, monkeypatch):
    use(monkeypatch, FakeClient(repo()))
    r = client.post("/api/onboard/github", json={"repo": "acme-labs/platform", "slug": "Bad Slug"})
    assert r.status_code == 422 and r.json()["detail"][0]["loc"] == ["slug"]


def test_create_bad_repo_text_is_422(client):
    assert client.post("/api/onboard/github", json={"repo": "not a repo"}).status_code == 422


def test_create_keeps_company_when_build_does_not_start(client, api_root, monkeypatch, runner):
    use(monkeypatch, FakeClient(repo()))

    def boom(*a, **k):
        raise RuntimeError("no thread for you")

    monkeypatch.setattr(runner, "start", boom)
    r = client.post("/api/onboard/github", json={"repo": "acme-labs/platform"})
    assert r.status_code == 201
    assert r.json()["build"] is None and "no thread" in r.json()["build_error"]
    assert registry.exists("acme_labs")


def test_company_reading_and_owner(api_root):
    company("falkordb", "FalkorDB", "FalkorDB/FalkorDB")
    assert onboard.company_reading("falkordb/falkordb").slug == "falkordb"
    assert onboard.company_reading("FalkorDB/falkordb-py") is None
    assert onboard.company_of_owner("falkordb").slug == "falkordb"
    assert onboard.company_of_owner("acme") is None
