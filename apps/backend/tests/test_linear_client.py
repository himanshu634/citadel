"""LinearClient: key header, rate-limit waits, retries; LinearSource validation."""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest
from brain.adapters.linear import LinearSource
from brain.adapters.linear import client as lc
from brain.adapters.linear.client import LinearClient, LinearError, LinearRateLimited
from pydantic import ValidationError

OK = {"data": {"viewer": {"organization": {"urlKey": "acme", "name": "Acme"}}}}
RATELIMITED = {
    "errors": [{"message": "Rate limit exceeded", "extensions": {"code": "RATELIMITED"}}]
}


@pytest.fixture
def slept(monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr(lc.time, "sleep", waits.append)
    monkeypatch.setattr(lc, "token", lambda: "lin_api_key")
    return waits


def make(handler, **kwargs) -> LinearClient:
    return LinearClient(log=lambda msg: None, transport=httpx.MockTransport(handler), **kwargs)


def sequence(responses: list[httpx.Response]):
    queue = iter(responses)
    return lambda request: next(queue)


def reset_in(seconds: float) -> str:
    return str(int((time.time() + seconds) * 1000))  # UTC epoch milliseconds


def test_sends_key_without_bearer(slept):
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=OK)

    with make(handler) as c:
        assert c.query("meta", {}) == OK["data"]
    assert seen[0].headers["Authorization"] == "lin_api_key"
    assert slept == []


def test_ratelimited_400_waits_until_reset_then_retries(slept):
    limited = httpx.Response(
        400, json=RATELIMITED, headers={"X-RateLimit-Requests-Reset": reset_in(30)}
    )
    with make(sequence([limited, httpx.Response(200, json=OK)])) as c:
        assert c.query("meta", {}) == OK["data"]
    assert len(slept) == 1
    assert slept[0] == pytest.approx(31, abs=2)


def test_ratelimited_without_reset_header_backs_off(slept):
    with make(sequence([httpx.Response(400, json=RATELIMITED), httpx.Response(200, json=OK)])) as c:
        c.query("meta", {})
    assert slept == [5]


def test_low_remaining_sleeps_after_success(slept):
    headers = {"X-RateLimit-Requests-Remaining": "10", "X-RateLimit-Requests-Reset": reset_in(20)}
    with make(sequence([httpx.Response(200, json=OK, headers=headers)])) as c:
        assert c.query("meta", {}) == OK["data"]
    assert len(slept) == 1
    assert slept[0] == pytest.approx(21, abs=2)


def test_plenty_remaining_does_not_sleep(slept):
    headers = {"X-RateLimit-Requests-Remaining": "900", "X-RateLimit-Requests-Reset": reset_in(20)}
    with make(sequence([httpx.Response(200, json=OK, headers=headers)])) as c:
        c.query("meta", {})
    assert slept == []


def test_5xx_backs_off_then_raises_after_attempts(slept):
    with make(sequence([httpx.Response(502)] * 3), attempts=3) as c:
        with pytest.raises(LinearError, match="kept failing") as exc:
            c.query("meta", {})
    assert not isinstance(exc.value, LinearRateLimited)
    assert slept == [5, 10]  # no sleep after the last attempt


def test_5xx_then_success(slept):
    with make(sequence([httpx.Response(503), httpx.Response(200, json=OK)])) as c:
        assert c.query("meta", {}) == OK["data"]
    assert slept == [5]


def test_ratelimited_to_the_end_raises_the_rate_limited_error(slept):
    with make(sequence([httpx.Response(400, json=RATELIMITED)] * 2), attempts=2) as c:
        with pytest.raises(LinearRateLimited):
            c.query("meta", {})


def test_graphql_error_raises_linear_error(slept):
    body = {"errors": [{"message": "Field 'nope' doesn't exist"}]}
    with make(sequence([httpx.Response(200, json=body)])) as c:
        with pytest.raises(LinearError, match="GraphQL errors in meta") as exc:
            c.query("meta", {})
    assert not isinstance(exc.value, LinearRateLimited)
    assert slept == []


def test_other_4xx_raises_without_retry(slept):
    with make(sequence([httpx.Response(401, text="Unauthorized")])) as c:
        with pytest.raises(LinearError, match="401"):
            c.query("meta", {})
    assert slept == []


def test_document_override_is_sent(slept):
    seen: list[bytes] = []

    def handler(request):
        seen.append(request.content)
        return httpx.Response(200, json=OK)

    with make(handler) as c:
        c.query("ignored", {"a": 1}, document="query X { viewer { id } }")
    assert b"query X" in seen[0] and b'"a"' in seen[0]


def test_missing_key_message(monkeypatch):
    monkeypatch.setattr(lc, "get_settings", lambda: type("S", (), {"linear_api_key": None})())
    with pytest.raises(LinearError, match="set LINEAR_API_KEY in .env"):
        lc.token()


def test_key_comes_from_settings(monkeypatch):
    monkeypatch.setattr(lc, "get_settings", lambda: type("S", (), {"linear_api_key": "k"})())
    assert lc.token() == "k"


def test_no_query_requests_email():
    queries = Path(lc.__file__).parent / "queries"
    docs = sorted(queries.glob("*.graphql"))
    assert {d.stem for d in docs} >= {"meta", "teams", "issues"}
    for doc in docs:
        assert "email" not in doc.read_text().lower(), doc.name


def test_issues_document_declares_the_variables_the_fetcher_sends():
    text = lc.graphql("issues")
    for var in (
        "$teams: [String!]!",
        "$since: DateTimeOrDuration!",
        "$first: Int!",
        "$after: String",
    ):
        assert var in text


def test_source_accepts_valid_config():
    s = LinearSource.model_validate(
        {"type": "linear", "workspace": "acme-inc", "teams": ["ENG", "P2"]}
    )
    assert s.workspace == "acme-inc" and s.teams == ["ENG", "P2"]
    assert LinearSource.model_validate({"type": "linear", "workspace": "acme"}).teams == []


@pytest.mark.parametrize(
    "bad",
    [
        {"workspace": "Acme"},  # upper case
        {"workspace": "acme inc"},
        {"workspace": ""},
        {"workspace": "acme", "teams": ["eng"]},  # lower case key
        {"workspace": "acme", "teams": ["1ENG"]},  # starts with a digit
        {"workspace": "acme", "teams": ["TOOLONGKEY"]},  # more than 7 characters
        {"workspace": "acme", "teams": [""]},
        {"workspace": "acme", "extra": 1},  # unknown field
    ],
)
def test_source_rejects_bad_workspace_and_team_keys(bad):
    with pytest.raises(ValidationError):
        LinearSource.model_validate({"type": "linear", **bad})
