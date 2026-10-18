"""Archive backends (GitHub, Linear, canonical_jsonl) and the session's budgets.

HTTP is mocked with httpx.MockTransport (recorded-shape payloads in tests/fixtures/*/archive/);
budget tests use a stub backend; graph tests use a throwaway slug and a temp repo root."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from brain import config, db, embeddings, loader, schema, tools
from brain.adapters.github import GithubSource
from brain.adapters.github import client as gh
from brain.adapters.linear import LinearSource
from brain.adapters.linear import client as lc
from brain.archive.backends import (
    Candidate,
    Fetched,
    GithubBackend,
    LinearBackend,
    OutOfScope,
    SourceFailed,
    backends_for,
)
from brain.archive.cache import ArchiveEntry, write_entry
from brain.archive.session import ArchiveSession, Budget, BudgetSpent, daily_loaded
from brain.canonical import Comment, Document, Link, WorkItem
from brain.config import CompanyConfig, get_settings
from brain.testing import FakeEmbedder, needs_graph, synthetic_company, write_company

FIXTURES = Path(__file__).parent / "fixtures"
SINCE = date(2026, 1, 1)


def fixture(path: str) -> dict:
    return json.loads((FIXTURES / path).read_text())


class Http:
    """A MockTransport handler that answers by the GraphQL document's operation and keeps every
    request body it saw."""

    def __init__(self, answers: dict[str, dict]) -> None:
        self.answers = answers
        self.seen: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.seen.append(body)
        for marker, payload in self.answers.items():
            if marker in body["query"]:
                return httpx.Response(200, json=payload)
        return httpx.Response(500, text=f"no answer for {body['query'][:80]}")

    def ops(self) -> list[str]:
        return [next((m for m in self.answers if m in b["query"]), "?") for b in self.seen]


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(gh, "token", lambda: "t0k")
    monkeypatch.setattr(lc, "token", lambda: "lin_key")
    monkeypatch.setattr(gh.time, "sleep", lambda s: None)
    monkeypatch.setattr(lc.time, "sleep", lambda s: None)


def company(permission: str, sources: list[dict], slug: str = "archtest_be") -> CompanyConfig:
    return CompanyConfig.model_validate(
        {
            "slug": slug,
            "name": slug,
            "data_permission": permission,
            "window": {"since": SINCE.isoformat()},
            "sources": sources,
        }
    )


GH_SOURCE = {"type": "github", "repo": "acme/widgets"}
META = {
    "nameWithOwner": "acme/widgets",
    "url": "https://github.com/acme/widgets",
    "isPrivate": False,
    "defaultBranch": "main",
}


def github(tmp_path, http: Http, *, permission="public", meta=META, known=None) -> GithubBackend:
    if meta is not None:
        (tmp_path / "meta.json").write_text(json.dumps(meta))
    known = known or {}
    cfg = company(permission, [GH_SOURCE])
    client = gh.GithubClient(log=lambda m: None, transport=httpx.MockTransport(http))

    def lookup(params):
        uid = known.get((params.get("container"), params.get("number"))) or known.get(
            params.get("uid")
        )
        return {"uid": uid} if uid else None

    return GithubBackend(cfg, GithubSource(**GH_SOURCE), tmp_path, lookup, client=client)


def test_github_fetch_by_number_builds_records(offline, tmp_path):
    http = Http({"issueOrPullRequest": fixture("github/archive/item_issue_812.json")})
    b = github(tmp_path, http, known={("acme/widgets", 900): "github:acme/widgets:pr:900"})
    f = b.fetch("#812")
    assert http.seen[0]["variables"] == {"owner": "acme", "name": "widgets", "number": 812}
    item = f.records[0]
    assert isinstance(item, WorkItem) and item.uid == "github:acme/widgets:issue:812"
    assert item.kind == "issue" and item.state == "closed"
    comments = [r for r in f.records if isinstance(r, Comment)]
    assert [c.author_login for c in comments] == ["bob"]  # the deleted account is skipped
    links = [(r.rel, r.to_uid) for r in f.records if isinstance(r, Link)]
    assert ("MENTIONS", "github:acme/widgets:pr:900") in links
    assert f.refs == ["github:acme/widgets#650", "github:acme/widgets#700"]
    assert f.candidate.id == f.candidate.ref == "github:acme/widgets#812"
    assert f.candidate.uid == item.uid and f.candidate.source_key == "github:acme/widgets"
    assert "mobile app refreshes daily" in f.text and item.title in f.text


def test_github_search_uses_window_cutoff(offline, tmp_path):
    http = Http({"search(": fixture("github/archive/search.json")})
    found = github(tmp_path, http).search("token rotation repo:other/secret", SINCE)
    q = http.seen[0]["variables"]["q"]
    assert "repo:acme/widgets" in q and "created:<2026-01-01" in q
    assert "other/secret" not in q  # a qualifier in the terms cannot widen the search
    assert [(c.id, c.kind) for c in found] == [
        ("github:acme/widgets#812", "issue"),
        ("github:acme/widgets#640", "pull_request"),
    ]  # another repo's hit and an empty node are dropped
    assert found[1].uid == "github:acme/widgets:pr:640"
    assert len(found[1].snippet) <= 300


@pytest.mark.parametrize(
    "ref, expected",
    [
        ("#812", "github:acme/widgets#812"),
        ("acme/widgets#812", "github:acme/widgets#812"),
        ("github:acme/widgets#812", "github:acme/widgets#812"),
        ("https://github.com/acme/widgets/pull/812", "github:acme/widgets#812"),
        ("https://github.com/acme/widgets/issues/812#issuecomment-1", "github:acme/widgets#812"),
        ("github:acme/widgets:pr:812", "github:acme/widgets#812"),
        ("other/repo#5", None),
        ("https://github.com/other/repo/issues/5", None),
        ("ENG-12", None),
    ],
)
def test_github_parse_ref(offline, tmp_path, ref, expected):
    assert github(tmp_path, Http({})).parse_ref(ref) == expected


def test_private_repo_refused(offline, tmp_path):
    http = Http({"issueOrPullRequest": fixture("github/archive/item_issue_812.json")})
    b = github(tmp_path, http, meta={**META, "isPrivate": True})
    with pytest.raises(PermissionError, match="private"):
        b.fetch("#812")
    with pytest.raises(PermissionError):
        b.search("tokens", SINCE)
    assert http.seen == []  # refused before any data query

    # no cached meta: one repo_meta query decides, and nothing else is asked
    repo_meta = {
        "data": {"repository": {**META, "isPrivate": True, "defaultBranchRef": {"name": "main"}}}
    }
    http = Http({"RepoMeta": repo_meta, "search(": fixture("github/archive/search.json")})
    with pytest.raises(PermissionError):
        github(tmp_path / "none", http, meta=None).search("tokens", SINCE)
    assert http.ops() == ["RepoMeta"]


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    (tmp_path / "companies").mkdir()
    return tmp_path


def test_backends_for_reads_the_company(root, offline):
    folder = root / "jsonl"
    (folder / "archive").mkdir(parents=True)
    plain = root / "plain"
    plain.mkdir()
    write_company(
        company(
            "own",
            [
                GH_SOURCE,
                {"type": "linear", "workspace": "acme", "teams": ["ENG"]},
                {"type": "canonical_jsonl", "path": str(folder)},
                {"type": "canonical_jsonl", "path": str(plain)},  # no archive/: no backend
            ],
            slug="archtest_bf",
        )
    )
    got = backends_for("archtest_bf")
    assert sorted(got) == [
        "canonical_jsonl:" + folder.as_posix(),
        "github:acme/widgets",
        "linear:acme",
    ]


def linear(http: Http, *, permission="synthetic", teams=("ENG",), known=()) -> LinearBackend:
    cfg = company(permission, [{"type": "linear", "workspace": "acme", "teams": list(teams)}])
    client = lc.LinearClient(log=lambda m: None, transport=httpx.MockTransport(http))
    source = LinearSource(type="linear", workspace="acme", teams=list(teams))

    def lookup(params):
        return {"uid": params["uid"]} if params.get("uid") in known else None

    return LinearBackend(cfg, source, lookup, client=client)


def test_linear_search_documents_to_document_records(offline):
    http = Http(
        {
            "searchIssues": fixture("linear/archive/search_issues.json"),
            "searchDocuments": fixture("linear/archive/search_documents.json"),
            "document(": fixture("linear/archive/document.json"),
        }
    )
    b = linear(http)
    found = b.search("billing retry", SINCE)
    doc_uid = "linear:doc:d1a2b3c4-0000-4000-8000-00000000d0c1"
    assert {c.uid for c in found} == {"linear:issue:0b7c2c4e-1111-4a2b-9c3d-000000000012", doc_uid}
    doc = next(c for c in found if c.kind == "document")
    f = b.fetch(doc.id)
    (record,) = f.records
    assert isinstance(record, Document)
    assert record.uid == doc_uid and record.source == "linear"
    assert record.title == "Billing retry policy" and "idempotency key" in record.body
    assert record.author_login == "carol"
    assert f.refs == [] and "kept for 24 hours" in f.text


def test_linear_fetch_by_key_is_canonical(offline):
    http = Http({"issue(": fixture("linear/archive/issue.json")})
    b = linear(http, known={"linear:issue:0b7c2c4e-1111-4a2b-9c3d-000000000007"})
    assert b.parse_ref("ENG-12") == "ENG-12"
    assert b.parse_ref("https://linear.app/acme/issue/ENG-12/billing") == "ENG-12"
    assert b.parse_ref("https://linear.app/other/issue/ENG-12/billing") is None
    assert b.parse_ref("OPS-3") is None  # not a configured team
    f = b.fetch("ENG-12")
    assert http.seen[0]["variables"] == {"id": "ENG-12"}
    uid = "linear:issue:0b7c2c4e-1111-4a2b-9c3d-000000000012"
    assert f.candidate.id == f.candidate.uid == f.candidate.ref == uid
    assert f.refs == ["linear:issue:0b7c2c4e-1111-4a2b-9c3d-000000000099"]  # 0007 is known
    assert [type(r).__name__ for r in f.records].count("Comment") == 1


def test_linear_refused_for_public_data(offline):
    http = Http({})
    with pytest.raises(PermissionError):
        linear(http, permission="public").search("billing", SINCE)
    assert http.seen == []


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_canonical_archive_search_and_fetch(root):
    folder = root / "synth"
    archive = folder / "archive"
    archive.mkdir(parents=True)
    old = "2023-02-01T00:00:00Z"
    _jsonl(
        archive / "work_items.jsonl",
        [
            {
                "uid": "wi:old-auth",
                "kind": "issue",
                "title": "Token rotation",
                "state": "closed",
                "body": "Rotate AUTH tokens daily.",
                "created_at": old,
                "author_login": "alice",
                "unresolved_refs": ["wi:older"],
            },
            {
                "uid": "wi:old-billing",
                "kind": "issue",
                "title": "Billing",
                "state": "closed",
                "body": "Retries.",
                "created_at": old,
            },
        ],
    )
    _jsonl(
        archive / "comments.jsonl",
        [
            {
                "uid": "c:1",
                "work_item_uid": "wi:old-auth",
                "author_login": "bob",
                "created_at": old,
                "body": "Agreed, daily.",
            },
            {
                "uid": "c:2",
                "work_item_uid": "wi:old-billing",
                "author_login": "bob",
                "created_at": old,
                "body": "no",
            },
        ],
    )
    _jsonl(
        archive / "links.jsonl",
        [
            {
                "rel": "MENTIONS",
                "from_uid": "wi:old-auth",
                "from_label": "WorkItem",
                "to_uid": "system:Auth",
                "to_label": "System",
            },
        ],
    )
    _jsonl(archive / "people.jsonl", [{"login": "alice"}, {"login": "bob"}, {"login": "zed"}])
    write_company(company("synthetic", [{"type": "canonical_jsonl", "path": str(folder)}]))
    (b,) = backends_for("archtest_be").values()

    assert [c.uid for c in b.search("auth TOKENS", SINCE)] == ["wi:old-auth"]
    assert b.search("auth billing", SINCE) == []  # every term must match
    assert b.search("auth", date(2023, 1, 1)) == []  # created after `before`
    assert b.parse_ref("wi:old-auth") == "wi:old-auth" and b.parse_ref("wi:nope") is None

    f = b.fetch("wi:old-auth")
    kinds = sorted(type(r).__name__ for r in f.records)
    assert kinds == ["Comment", "Link", "Person", "Person", "WorkItem"]
    assert f.refs == ["wi:older"]
    assert "Agreed, daily." in f.text and f.candidate.ref == "wi:old-auth"


# --- the session ------------------------------------------------------------------------------


class Stub:
    """A backend over a dict of items: id -> refs. Counts its calls. "K-<id>" is an alias that
    parses to itself (like a Linear key) and fetches as <id> (like the key's uuid)."""

    key = "stub"

    def __init__(self, items: dict[str, list[str]]) -> None:
        self.items = items
        self.calls = 0

    def parse_ref(self, ref: str) -> str | None:
        if ref.startswith("K-") and ref[2:] in self.items:
            return ref
        ref = ref.removeprefix("alias:")
        return ref if ref in self.items else None

    def match(self, item_id: str) -> dict:
        return {"uid": item_id}

    def search(self, terms: str, before: date) -> list[Candidate]:
        self.calls += 1
        return []

    def fetch(self, item_id: str) -> Fetched:
        self.calls += 1
        item_id = item_id.removeprefix("K-")
        item = WorkItem(
            uid=item_id,
            kind="issue",
            title=f"Item {item_id}",
            state="closed",
            created_at="2023-03-01T00:00:00Z",
            unresolved_refs=self.items[item_id],
        )
        comment = Comment(
            uid=f"c:{item_id}",
            work_item_uid=item_id,
            author_login="bob",
            created_at="2023-03-02T00:00:00Z",
            body="old comment",
        )
        cand = Candidate(
            id=item_id, uid=item_id, ref=item_id, source_key="stub", kind="issue", title=item.title
        )
        return Fetched(
            candidate=cand, text=item.title, records=[item, comment], refs=item.unresolved_refs
        )


SLUG = "archtest_session"


@pytest.fixture
def session_company(root):
    write_company(synthetic_company(SLUG))
    return SLUG


def session(stub: Stub, **budget) -> ArchiveSession:
    b = Budget(**{"calls": 6, "items": 3, "depth": 2, **budget})
    return ArchiveSession(SLUG, b, backends={"stub": stub})


def test_session_call_budget(session_company):
    stub = Stub({f"i{n}": [] for n in range(10)})
    s = session(stub, calls=6)
    for n in range(3):
        s.search("stub", "anything")
        s.fetch("stub", f"i{n}")
    with pytest.raises(BudgetSpent, match="calls") as exc:
        s.search("stub", "one more")
    assert exc.value.budget == "calls"
    assert s.calls_used == 6 and stub.calls == 6
    with pytest.raises(OutOfScope):
        s.search("nowhere", "x")


def test_session_depth_budget(session_company):
    stub = Stub({"a": ["b"], "b": ["c"], "c": ["d"], "d": [], "e": []})
    s = session(stub, calls=10, depth=2)
    for item in ("a", "b", "c"):
        s.fetch("stub", item)
    assert [s.depth[u] for u in ("a", "b", "c")] == [0, 1, 2]
    with pytest.raises(BudgetSpent, match="depth") as exc:
        s.fetch("stub", "d")
    assert exc.value.budget == "depth"
    assert s.calls_used == 3  # refused before the call
    s.fetch("stub", "e")  # an item no fetched one points at starts a new trail
    assert s.depth["e"] == 0


def test_ids_for_lists_every_id_an_item_was_fetched_under(session_company):
    s = session(Stub({"a": []}))
    s.fetch("stub", "K-a")
    s.fetch("stub", "alias:a")
    assert s.ids_for("a") == {"a", "K-a", "alias:a"}
    assert s.ids_for("nope") == set()


def test_fetch_is_cached_not_recounted(session_company):
    stub = Stub({"a": []})
    s = session(stub)
    first = s.fetch("stub", "a")
    assert s.fetch("stub", "a") is first
    assert s.fetch("stub", "alias:a") is first  # another id for the same item
    assert s.calls_used == 1 and stub.calls == 1
    assert s.fetched == {"a": first}


@pytest.fixture
def warm_flags():
    yield
    get_settings.cache_clear()
    embeddings.set_embedder(None)


def test_is_warm_never_builds_an_embedder(monkeypatch, warm_flags):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fastembed")
    get_settings.cache_clear()
    embeddings.set_embedder(None)
    assert embeddings.is_warm() is False
    assert embeddings._default is None  # nothing was constructed
    cold = embeddings.FastEmbedEmbedder("m", 4)
    monkeypatch.setattr(embeddings, "_default", cold)
    assert embeddings.is_warm() is False  # built, model not loaded
    cold._engine = object()
    assert embeddings.is_warm() is True
    embeddings.set_embedder(FakeEmbedder())
    assert embeddings.is_warm() is True


# --- graph tests ------------------------------------------------------------------------------


@pytest.fixture
def graph(session_company):
    db.delete_graph(SLUG)
    schema.apply_schema(SLUG)
    yield SLUG
    db.delete_graph(SLUG)


def _today_entry(uid: str, at: str) -> ArchiveEntry:
    return ArchiveEntry(
        source_key="stub",
        item_id=uid,
        uid=uid,
        ref=uid,
        archived_at=at,
        request="earlier",
        records=[],
    )


@needs_graph
def test_load_respects_item_and_daily_cap(graph, monkeypatch, warm_flags):
    now = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)
    stub = Stub({u: [] for u in ("a", "b", "c", "d")})
    s = ArchiveSession(
        SLUG, Budget(calls=10, items=2, depth=2), backends={"stub": stub}, now=lambda: now
    )
    for u in ("a", "b", "c"):
        s.fetch("stub", u)
    with pytest.raises(ValueError, match="not fetched"):
        s.load("why?", ["d"], superseded={})
    assert s.load("why?", ["a", "b", "c"], superseded={"a": "b"}) == ["a", "b"]
    with pytest.raises(BudgetSpent, match="items"):
        s.load("why?", ["c"], superseded={})  # the item budget is per session
    a = tools.get_entity(SLUG, "a")
    assert a.archived is True
    old_comment = db.graph(SLUG).query(
        "MATCH (:Person)-[:COMMENTED_ON]->(:WorkItem {uid:'a'}) RETURN count(*)"
    )
    assert old_comment.result_set[0][0] == 1  # the 2023 comment is kept (window exemption)
    sup = db.graph(SLUG).query("MATCH (w:WorkItem {uid:'a'}) RETURN w.superseded_by")
    assert sup.result_set[0][0] == "b"
    assert daily_loaded(SLUG, now.date()) == 2

    # daily cap: 2 today + 1 yesterday already archived, cap 3 -> room for 1 more
    monkeypatch.setenv("ARCHIVIST_DAILY_CAP", "3")
    get_settings.cache_clear()
    write_entry(SLUG, _today_entry("y", "2026-10-16T23:59:00Z"))
    s2 = ArchiveSession(
        SLUG, Budget(calls=10, items=5, depth=2), backends={"stub": stub}, now=lambda: now
    )
    s2.fetch("stub", "c")
    s2.fetch("stub", "d")
    assert s2.load("why?", ["c", "d"], superseded={}) == ["c"]
    assert daily_loaded(SLUG, now.date()) == 3
    with pytest.raises(BudgetSpent, match="daily_cap"):
        s2.load("why?", ["d"], superseded={})


@needs_graph
def test_session_lookup_reads_the_brain(graph, offline, tmp_path):
    pr = WorkItem(
        uid="github:acme/widgets:pr:900",
        kind="pull_request",
        number=900,
        container="acme/widgets",
        title="Fix",
        state="merged",
        created_at="2026-05-01T00:00:00Z",
        url="https://github.com/acme/widgets/pull/900",
    )
    loader.load(SLUG, [pr])
    (tmp_path / "gh").mkdir()
    b = github(tmp_path / "gh", Http({}))
    s = ArchiveSession(SLUG, Budget(calls=1, items=1, depth=1), backends={b.key: b})
    assert s.lookup("#900")["uid"] == pr.uid
    assert s.lookup("https://github.com/acme/widgets/issues/900")["uid"] == pr.uid
    assert s.lookup(pr.uid)["uid"] == pr.uid
    assert s.lookup("#5") is None
    assert s.calls_used == 0


def test_rate_limits_fail_fast_on_the_ask_path(monkeypatch):
    """A rate-limit wait longer than MAX_WAIT fails the call (SourceFailed) instead of holding
    an Ask answer for a minute (GitHub retry-after) or an hour (Linear's reset)."""
    slept: list[float] = []
    monkeypatch.setattr(gh, "token", lambda: "t0k")
    monkeypatch.setattr(lc, "token", lambda: "lin_key")
    monkeypatch.setattr(gh.time, "sleep", slept.append)
    monkeypatch.setattr(lc.time, "sleep", slept.append)

    def limited_github(request):
        return httpx.Response(403, text="API rate limit exceeded", headers={"retry-after": "60"})

    client = GithubBackend.new_client()
    client._http = httpx.Client(transport=httpx.MockTransport(limited_github))
    with pytest.raises(gh.GithubRateLimited):
        client.query("archive_search", {"q": "x"})

    reset = str(int((datetime.now(UTC).timestamp() + 1800) * 1000))  # 30 minutes out

    def limited_linear(request):
        errors = [{"message": "slow down", "extensions": {"code": "RATELIMITED"}}]
        return httpx.Response(
            400, json={"errors": errors}, headers={"X-RateLimit-Requests-Reset": reset}
        )

    lin = LinearBackend.new_client()
    lin._http = httpx.Client(transport=httpx.MockTransport(limited_linear))
    b = LinearBackend(
        company("synthetic", [{"type": "linear", "workspace": "acme"}]),
        LinearSource(type="linear", workspace="acme"),
        lambda params: None,
        client=lin,
    )
    with pytest.raises(SourceFailed, match="kept failing"):
        b.fetch("ENG-1")
    assert slept == []


@needs_graph
def test_load_embeds_only_the_loaded_items_when_warm(graph, warm_flags):
    other = WorkItem(uid="wi:other", kind="issue", title="Unrelated pending text", state="open",
                     body="Not embedded yet.", created_at="2026-05-01T00:00:00Z")  # fmt: skip
    loader.load(SLUG, [other])
    stub = Stub({"a": [], "b": []})

    def embedded(uid: str) -> list[bool]:
        res = db.graph(SLUG).query(
            "MATCH (c:Chunk)-[:FROM]->({uid: $uid}) RETURN c.embedding IS NOT NULL", {"uid": uid}
        )
        return [row[0] for row in res.result_set]

    cold = ArchiveSession(SLUG, Budget(calls=5, items=5, depth=2), backends={"stub": stub})
    cold.fetch("stub", "a")
    assert cold.load("why?", ["a"], superseded={}) == ["a"]
    assert embedded("a") and not any(embedded("a"))  # no embedder in memory: chunks wait

    embeddings.set_embedder(FakeEmbedder())
    warm = ArchiveSession(SLUG, Budget(calls=5, items=5, depth=2), backends={"stub": stub})
    warm.fetch("stub", "b")
    warm.load("why?", ["b"], superseded={})
    assert embedded("b") and all(embedded("b"))
    assert not any(embedded("wi:other")) and not any(embedded("a"))  # the backlog waits


def test_depth_holds_through_aliases(session_company):
    """Parents list uids; fetching by key must still count the hops."""
    stub = Stub({"u1": ["u2"], "u2": ["u3"], "u3": ["u4"], "u4": []})
    s = session(stub, calls=10, depth=2)
    s.fetch("stub", "u1")
    s.fetch("stub", "K-u2")
    s.fetch("stub", "K-u3")
    assert [s.depth[u] for u in ("u1", "u2", "u3")] == [0, 1, 2]
    with pytest.raises(BudgetSpent, match="depth") as exc:
        s.fetch("stub", "K-u4")
    assert exc.value.budget == "depth"
    assert "u4" not in s.fetched  # too deep: never loadable
    assert s.calls_used == 4  # the call was made before its uid was known

    # the request's own refs are depth 0, also when fetched by an alias
    s = ArchiveSession(
        SLUG, Budget(calls=10, items=3, depth=2), backends={"stub": stub}, start_refs=["u3"]
    )
    s.fetch("stub", "u1")
    s.fetch("stub", "u2")
    s.fetch("stub", "K-u3")
    assert s.depth["u3"] == 0
    s.fetch("stub", "K-u4")
    assert s.depth["u4"] == 1


@needs_graph
def test_superseded_pair_applies_only_to_loaded_items(graph):
    windowed = [
        WorkItem(uid=uid, kind="issue", title=uid, state="open", created_at="2026-05-01T00:00:00Z")
        for uid in ("wi:new", "b")  # "b" also has a windowed copy, so a mark would show
    ]
    loader.load(SLUG, windowed)
    stub = Stub({"a": [], "b": []})
    s = ArchiveSession(SLUG, Budget(calls=5, items=1, depth=2), backends={"stub": stub})
    s.fetch("stub", "a")
    s.fetch("stub", "b")
    loaded = s.load("why?", ["a", "b"], superseded={"a": "wi:new", "b": "wi:new", "a2": "x"})
    assert loaded == ["a"]
    assert s.superseded == {"a": "wi:new"}
    rows = db.graph(SLUG).query(
        "MATCH (w:WorkItem) WHERE w.superseded_by IS NOT NULL RETURN w.uid ORDER BY w.uid"
    )
    assert [r[0] for r in rows.result_set] == ["a"]


@needs_graph
def test_supersession_survives_rebuild(graph):
    from brain import pipeline

    pipeline.ingest(SLUG, full=True)  # the synthetic company: synthetic:pr:1 is windowed
    stub = Stub({"a": []})
    s = ArchiveSession(SLUG, Budget(calls=5, items=5, depth=2), backends={"stub": stub})
    s.fetch("stub", "a")
    s.load("why?", ["a"], superseded={"a": "synthetic:pr:1"})

    def superseded() -> list:
        return (
            db.graph(SLUG)
            .query(
                "MATCH (a:WorkItem {uid:'a'})-[:SUPERSEDED_BY]->(b) RETURN a.superseded_by, b.uid"
            )
            .result_set
        )

    assert superseded() == [["synthetic:pr:1", "synthetic:pr:1"]]
    db.delete_graph(SLUG)
    schema.apply_schema(SLUG)
    pipeline.ingest(SLUG, full=True)  # the archive loads before the windowed item exists
    assert superseded() == [["synthetic:pr:1", "synthetic:pr:1"]]
