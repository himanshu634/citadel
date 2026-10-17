"""Archive backends: search and fetch one configured source's items older than the window.

Why: the Archivist finds items the build cut off (a 2023 issue, an old ticket). Every external
call it makes lives here, in the brain package, as a named query whose parameters are the only
thing the model chooses (terms, a number, an id). Each backend turns what it fetched into
canonical records with its adapter's own per-item code, so an archived item loads like a
windowed one. One backend per source of the company YAML (`backends_for`):
- `github`: one per repo. Same data rule as its fetch: a private repo is refused unless
  `data_permission: own` (checked before any data query, from the cached meta or one repo_meta
  query). Item ids are refs, `github:<owner>/<repo>#<n>`.
- `linear`: the workspace (`own`/`synthetic` data only), issues and documents, scoped to the
  configured teams. Item ids are uids, `linear:issue:<uuid>` / `linear:doc:<id>`; a key
  ("ENG-12") also fetches, and comes back under its uid.
- `canonical_jsonl`: a source folder with an `archive/` subfolder (the synthetic company's held
  back items). Item ids are uids.

`lookup` (the brain, through `lookup_node`) says which refs of a fetched item are already
loaded: those become links, the rest the item's `unresolved_refs` (= `Fetched.refs`).
Retries: the clients retry rate limits and 5xx inside one call (3 attempts, each wait at most
`MAX_WAIT`: a rate-limit window is never waited out on the Ask path); what still fails is
`SourceFailed`.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, field_validator

from brain import adapters, db
from brain.adapters.canonical_jsonl import FILES, CanonicalJsonlSource, _read
from brain.adapters.github import GithubSource
from brain.adapters.github import client as gh
from brain.adapters.github.fetch import check_permission as github_permission
from brain.adapters.github.transform import PathIndex, Repo, github_ref, issue_records, pr_records
from brain.adapters.linear import client as lc
from brain.adapters.linear.fetch import check_permission as linear_permission
from brain.adapters.linear.source import LinearSource
from brain.adapters.linear.transform import document_record, issue_uid, ticket_records
from brain.adapters.runs import nodes, read_json
from brain.canonical import (
    CanonicalRecord,
    Comment,
    Document,
    Link,
    Person,
    Review,
    WorkItem,
    person_uid,
    to_utc,
)
from brain.config import CompanyConfig, load_company, raw_dir

MAX_RESULTS = 10  # candidates per search
SNIPPET = 300  # characters of text per candidate
ATTEMPTS = 3  # tries per external call (rate limits and 5xx back off in between)
TIMEOUT = 30  # seconds per HTTP request
MAX_WAIT = 10  # seconds a retry may wait; a longer rate-limit wait fails the call instead

# lookup(params) -> the brain node or None; params as archive_lookup takes them
Lookup = Callable[[dict[str, Any]], dict[str, Any] | None]


class ArchiveError(RuntimeError):
    """An archive call that cannot be answered. The message is a sentence for a person."""


class OutOfScope(ArchiveError):
    """The ref or item is not in a source of this company (another repo, team or workspace)."""


class NotFound(ArchiveError):
    """The source has no such item."""


class SourceFailed(ArchiveError):
    """The source kept failing (rate limit, 5xx, network) after its retries."""


class Candidate(BaseModel):
    """One search hit (or the fetched item itself), cut to what the model needs."""

    id: str  # what `fetch` takes
    uid: str  # the node uid it loads as
    ref: str  # what other items carry in `unresolved_refs` for it
    source_key: str
    kind: str  # pull_request | issue | ticket | thread | document
    title: str
    date: dt.datetime | None = None
    url: str | None = None
    snippet: str = ""

    @field_validator("snippet")
    @classmethod
    def _cut(cls, v: str) -> str:
        return " ".join(v.split())[:SNIPPET]


@dataclass
class Fetched:
    candidate: Candidate
    text: str  # title, body and comments: what a find's quote is checked against
    records: list[CanonicalRecord]  # the item first, then its comments, reviews, links, people
    refs: list[str]  # the item's unresolved_refs: items it points at that the brain lacks


class Backend(Protocol):
    key: str  # the adapter key of its source, e.g. "github:acme/widgets"

    def search(self, terms: str, before: dt.date) -> list[Candidate]: ...

    def fetch(self, item_id: str) -> Fetched: ...

    def parse_ref(self, ref: str) -> str | None:
        """The item id when this backend owns `ref` (no network), else None."""
        ...

    def match(self, item_id: str) -> dict[str, Any]:
        """archive_lookup params that find this item in the brain."""
        ...


def lookup_node(slug: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """The brain node `params` (uid / container + number / key / url) finds, or None."""
    full = {"uid": None, "container": None, "number": None, "key": None, "url": None, **params}
    rows = db.run(slug, "load/archive_lookup", full, read_only=True)
    return rows[0] if rows else None


def _memo(lookup: Lookup) -> Lookup:
    seen: dict[tuple, dict[str, Any] | None] = {}

    def cached(params: dict[str, Any]) -> dict[str, Any] | None:
        key = tuple(sorted(params.items()))
        if key not in seen:
            seen[key] = lookup(params)
        return seen[key]

    return cached


def _text(*parts: str | None) -> str:
    return "\n\n".join(p for p in parts if p)


def _date(value: str | None) -> dt.datetime | None:
    return to_utc(dt.datetime.fromisoformat(value.replace("Z", "+00:00"))) if value else None


def _call(what: str, run: Callable[[], dict]) -> dict:
    try:
        return run()
    except (gh.GithubError, lc.LinearError, httpx.HTTPError) as e:
        raise SourceFailed(f"{what} failed: {e}") from e


# --- GitHub -----------------------------------------------------------------------------------

QUALIFIER_RE = re.compile(r"\S*:\S*")  # "repo:x", "created:>..": the backend sets those itself


class GithubBackend:
    def __init__(
        self,
        company: CompanyConfig,
        source: GithubSource,
        cache: Path,
        lookup: Lookup,
        client: gh.GithubClient | None = None,
    ) -> None:
        self.key = f"github:{source.repo}"
        self._company = company
        self._include = set(source.include)
        self._cache = cache
        self._lookup = lookup
        self._client = client
        self._owner, self._name = source.repo.split("/")
        self._meta: dict[str, Any] | None = read_json(cache / "meta.json")
        # uids and refs use GitHub's spelling of the repo, as the build wrote them
        self.repo = (self._meta or {}).get("nameWithOwner") or source.repo
        repo = re.escape(source.repo)
        self._ref_re = re.compile(rf"(?:github:)?{repo}#(\d+)", re.I)
        self._uid_re = re.compile(rf"github:{repo}:(?:issue|pr):(\d+)", re.I)
        self._url_re = re.compile(
            rf"https?://(?:www\.)?github\.com/{repo}/(?:issues|pull)/(\d+)(?:[/?#].*)?", re.I
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    @staticmethod
    def new_client() -> gh.GithubClient:
        return gh.GithubClient(
            log=lambda msg: None,
            timeout=TIMEOUT,
            attempts=ATTEMPTS,
            wait_for_rate_limit=False,
            max_wait=MAX_WAIT,
        )

    def _query(self, name: str, variables: dict[str, Any]) -> dict:
        client = self._client = self._client or self.new_client()
        return _call(f"GitHub {name} for {self.repo}", lambda: client.query(name, variables))

    def _repo(self) -> Repo:
        """The repo, after the private-repo check (one repo_meta query when nothing is cached)."""
        if self._meta is None:
            found = self._query("repo_meta", {"owner": self._owner, "name": self._name})
            repo = found["repository"]
            if repo is None:
                raise NotFound(f"GitHub repository {self.key} was not found (or no access).")
            self._meta = {
                "nameWithOwner": repo["nameWithOwner"],
                "url": repo["url"],
                "isPrivate": repo["isPrivate"],
                "defaultBranch": (repo.get("defaultBranchRef") or {}).get("name") or "main",
            }
        github_permission(self._meta, self._company)
        meta = self._meta
        return Repo(meta["nameWithOwner"], meta["url"], meta.get("defaultBranch") or "main")

    def _number(self, ref: str) -> int | None:
        ref = ref.strip()
        if m := re.fullmatch(r"#(\d+)", ref):
            return int(m.group(1))
        for pattern in (self._ref_re, self._uid_re, self._url_re):
            if m := pattern.fullmatch(ref):
                return int(m.group(1))
        return None

    def parse_ref(self, ref: str) -> str | None:
        n = self._number(ref)
        return github_ref(self.repo, n) if n is not None else None

    def match(self, item_id: str) -> dict[str, Any]:
        return {"container": self.repo, "number": self._number(item_id)}

    def _candidate(self, repo: Repo, node: dict[str, Any]) -> Candidate:
        n = node["number"]
        pr = node["__typename"] == "PullRequest"
        return Candidate(
            id=github_ref(repo.name, n),
            uid=repo.pr(n) if pr else repo.issue(n),
            ref=github_ref(repo.name, n),
            source_key=self.key,
            kind="pull_request" if pr else "issue",
            title=node["title"],
            date=_date(node.get("createdAt")),
            url=node.get("url"),
            snippet=node.get("body") or "",
        )

    def search(self, terms: str, before: dt.date) -> list[Candidate]:
        repo = self._repo()
        words = " ".join(QUALIFIER_RE.sub(" ", terms).split())
        if not words:
            return []
        q = f"repo:{repo.name} {words} created:<{before.isoformat()}"
        found = []
        for node in nodes(self._query("archive_search", {"q": q})["search"]):
            if not node.get("number"):
                continue  # a result type the query does not select
            if (node.get("repository") or {}).get("nameWithOwner", "").lower() != (
                repo.name.lower()
            ):
                continue
            if node["__typename"] == "PullRequest" and "pull_requests" not in self._include:
                continue
            if node["__typename"] == "Issue" and "issues" not in self._include:
                continue
            found.append(self._candidate(repo, node))
        return found[:MAX_RESULTS]

    def fetch(self, item_id: str) -> Fetched:
        n = self._number(item_id)
        if n is None:
            raise OutOfScope(f"{item_id} is not an issue or pull request of {self.key}.")
        repo = self._repo()
        variables = {"owner": self._owner, "name": self._name, "number": n}
        node = (self._query("archive_item", variables)["repository"] or {}).get(
            "issueOrPullRequest"
        )
        if not node:
            raise NotFound(f"{github_ref(repo.name, n)} was not found.")
        lookup = _memo(self._lookup)

        def number_uid(k: int) -> str | None:
            hit = lookup({"container": repo.name, "number": k})
            return hit["uid"] if hit else None

        tree_file = self._cache / "tree.txt"
        paths = PathIndex(
            tree_file.read_text().splitlines() if tree_file.exists() else [], self._company
        )
        if node["__typename"] == "PullRequest":
            if "pull_requests" not in self._include:
                raise OutOfScope(f"{self.key} is configured without pull requests.")
            include = {"pull_requests"} | ({"reviews"} & self._include)
            records = list(pr_records(repo, node, include, number_uid, paths))
        else:
            if "issues" not in self._include:
                raise OutOfScope(f"{self.key} is configured without issues.")
            records = list(issue_records(repo, node, number_uid, paths))
        item = records[0]
        assert isinstance(item, WorkItem)
        comments = [c.body for c in records if isinstance(c, Comment)]
        return Fetched(
            candidate=self._candidate(repo, node),
            text=_text(item.title, item.body, *comments),
            records=records,
            refs=list(item.unresolved_refs),
        )


# --- Linear -----------------------------------------------------------------------------------

KEY_RE = re.compile(r"([A-Z][A-Z0-9]{0,6})-(\d+)")
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
LINEAR_URL_RE = re.compile(r"https?://linear\.app/([\w-]+)/(issue|document)/([^/?#]+)(?:[/?#].*)?")
DOC_PREFIX = "linear:doc:"
ISSUE_PREFIX = "linear:issue:"


def _interleave(a: list, b: list) -> Iterator:
    for i in range(max(len(a), len(b))):
        yield from (x[i] for x in (a, b) if i < len(x))


class LinearBackend:
    def __init__(
        self,
        company: CompanyConfig,
        source: LinearSource,
        lookup: Lookup,
        client: lc.LinearClient | None = None,
    ) -> None:
        self.key = f"linear:{source.workspace}"
        self._company = company
        self._workspace = source.workspace
        self._teams = set(source.teams)  # empty: every team
        self._lookup = lookup
        self._client = client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def _query(self, name: str, variables: dict[str, Any]) -> dict:
        linear_permission(self._company)  # before any data query
        client = self._client = self._client or self.new_client()
        return _call(f"Linear {name}", lambda: client.query(name, variables))

    @staticmethod
    def new_client() -> lc.LinearClient:
        return lc.LinearClient(
            log=lambda msg: None, timeout=TIMEOUT, attempts=ATTEMPTS, max_wait=MAX_WAIT
        )

    def _team_ok(self, team: str | None) -> bool:
        return not self._teams or team in self._teams

    def parse_ref(self, ref: str) -> str | None:
        ref = ref.strip()
        if ref.startswith((ISSUE_PREFIX, DOC_PREFIX)) and ref.split(":", 2)[2]:
            return ref
        if UUID_RE.fullmatch(ref):
            return issue_uid(ref.lower())
        if m := KEY_RE.fullmatch(ref):
            return ref if self._team_ok(m.group(1)) else None
        if m := LINEAR_URL_RE.fullmatch(ref):
            workspace, kind, tail = m.groups()
            if workspace != self._workspace:
                return None
            if kind == "document":
                return DOC_PREFIX + tail.rsplit("-", 1)[-1]  # "<title>-<slugId>"
            return tail if KEY_RE.fullmatch(tail) and self._team_ok(tail.split("-")[0]) else None
        return None

    def match(self, item_id: str) -> dict[str, Any]:
        if item_id.startswith((ISSUE_PREFIX, DOC_PREFIX)):
            return {"uid": item_id}
        return {"key": item_id}

    def search(self, terms: str, before: dt.date) -> list[Candidate]:
        cutoff = dt.datetime.combine(before, dt.time.min, tzinfo=dt.UTC)
        filt: dict[str, Any] = {"createdAt": {"lt": cutoff.isoformat()}}
        if self._teams:
            filt["team"] = {"key": {"in": sorted(self._teams)}}
        found = self._query("archive_search_issues", {"term": terms, "filter": filt})
        issues = []
        for node in nodes(found["searchIssues"]):
            created = _date(node.get("createdAt"))
            if not self._team_ok((node.get("team") or {}).get("key")):
                continue
            if created is not None and created >= cutoff:
                continue
            issues.append(
                Candidate(
                    id=issue_uid(node["id"]),
                    uid=issue_uid(node["id"]),
                    ref=issue_uid(node["id"]),
                    source_key=self.key,
                    kind="ticket",
                    title=f"{node['identifier']} {node['title']}",
                    date=created,
                    url=node.get("url"),
                    snippet=node.get("description") or "",
                )
            )
        # Documents: a build never loads them, so any date is "not in the brain".
        docs = [
            self._doc_candidate(node)
            for node in nodes(
                self._query("archive_search_documents", {"term": terms})["searchDocuments"]
            )
        ]
        return list(_interleave(issues, docs))[:MAX_RESULTS]

    def _doc_candidate(self, node: dict[str, Any]) -> Candidate:
        uid = DOC_PREFIX + node["id"]
        return Candidate(
            id=uid,
            uid=uid,
            ref=uid,
            source_key=self.key,
            kind="document",
            title=node.get("title") or node["id"],
            date=_date(node.get("updatedAt") or node.get("createdAt")),
            url=node.get("url"),
            snippet=node.get("content") or "",
        )

    def fetch(self, item_id: str) -> Fetched:
        target = self.parse_ref(item_id)
        if target is None:
            raise OutOfScope(f"{item_id} is not a ticket or document of {self.key}.")
        if target.startswith(DOC_PREFIX):
            doc_id = target.removeprefix(DOC_PREFIX)
            node = self._query("archive_document", {"id": doc_id})["document"]
            if not node:
                raise NotFound(f"Linear document {doc_id} was not found.")
            doc = document_record(node)
            return Fetched(
                candidate=self._doc_candidate(node),
                text=_text(doc.title, doc.body),
                records=[doc],
                refs=[],
            )
        node = self._query("archive_issue", {"id": target.removeprefix(ISSUE_PREFIX)})["issue"]
        if not node:
            raise NotFound(f"Linear issue {item_id} was not found.")
        if not self._team_ok(node["team"]["key"]):
            raise OutOfScope(
                f"{node['identifier']} is in team {node['team']['key']}, which "
                f"{self.key} does not include."
            )
        lookup = _memo(self._lookup)
        records = list(ticket_records(node, lambda i: lookup({"uid": issue_uid(i)}) is not None))
        ticket = records[0]
        assert isinstance(ticket, WorkItem)
        comments = [c.body for c in records if isinstance(c, Comment)]
        return Fetched(
            candidate=Candidate(
                id=ticket.uid,
                uid=ticket.uid,
                ref=ticket.uid,
                source_key=self.key,
                kind="ticket",
                title=f"{ticket.key} {ticket.title}",
                date=ticket.created_at,
                url=ticket.url,
                snippet=ticket.body,
            ),
            text=_text(ticket.title, ticket.body, *comments),
            records=records,
            refs=list(ticket.unresolved_refs),
        )


# --- canonical_jsonl --------------------------------------------------------------------------


class JsonlArchiveBackend:
    """The `archive/` subfolder of a canonical_jsonl source: the same files as the source,
    holding items older than the window. Search is a case-insensitive all-terms match on the
    title and body of its work items and documents."""

    def __init__(self, key: str, folder: Path) -> None:
        self.key = key
        self._folder = folder
        self._records: list[CanonicalRecord] | None = None

    def _all(self) -> list[CanonicalRecord]:
        if self._records is None:
            self._records = [
                rec
                for name, model in FILES.items()
                if (self._folder / name).exists()
                for rec in _read(self._folder / name, model)
            ]
        return self._records

    def _items(self) -> dict[str, WorkItem | Document]:
        return {r.uid: r for r in self._all() if isinstance(r, (WorkItem, Document))}

    def parse_ref(self, ref: str) -> str | None:
        ref = ref.strip()
        return ref if ref in self._items() else None

    def match(self, item_id: str) -> dict[str, Any]:
        return {"uid": item_id}

    def _candidate(self, item: WorkItem | Document) -> Candidate:
        if isinstance(item, WorkItem):
            kind, when = item.kind, item.created_at
        else:
            kind, when = "document", item.updated_at
        return Candidate(
            id=item.uid,
            uid=item.uid,
            ref=item.uid,
            source_key=self.key,
            kind=kind,
            title=item.title,
            date=to_utc(when),
            url=item.url,
            snippet=item.body,
        )

    def search(self, terms: str, before: dt.date) -> list[Candidate]:
        words = terms.lower().split()
        if not words:
            return []
        found = []
        for item in self._items().values():
            text = f"{item.title} {item.body}".lower()
            when = item.created_at if isinstance(item, WorkItem) else item.updated_at
            if all(w in text for w in words) and (when is None or when.date() < before):
                found.append(self._candidate(item))
        return found[:MAX_RESULTS]

    def fetch(self, item_id: str) -> Fetched:
        item = self._items().get(item_id.strip())
        if item is None:
            raise NotFound(f"{item_id} is not in the archive of {self.key}.")
        uid = item.uid
        records: list[CanonicalRecord] = [item]
        logins = {item.author_login, *(getattr(item, "assignees", None) or [])}
        for r in self._all():
            if isinstance(r, Comment) and r.work_item_uid == uid:
                records.append(r)
                logins.add(r.author_login)
            elif isinstance(r, Review) and r.work_item_uid == uid:
                records.append(r)
                logins.add(r.reviewer_login)
            elif isinstance(r, Link) and uid in (r.from_uid, r.to_uid):
                records.append(r)
        wanted = {person_uid(login) for login in logins if login}
        records += [r for r in self._all() if isinstance(r, Person) and r.uid in wanted]
        comments = [r.body for r in records if isinstance(r, Comment)]
        return Fetched(
            candidate=self._candidate(item),
            text=_text(item.title, item.body, *comments),
            records=records,
            refs=list(item.unresolved_refs) if isinstance(item, WorkItem) else [],
        )


# --- the company's backends -------------------------------------------------------------------


def backends_for(slug: str, lookup: Lookup | None = None) -> dict[str, Backend]:
    """One backend per archivable source of companies/<slug>.yaml, by source key. No network:
    clients are made on the first call, and a refused source (a private repo, Linear for public
    data) refuses then, with the reason."""
    cfg = load_company(slug)
    lookup = lookup or partial(lookup_node, slug)
    out: dict[str, Backend] = {}
    for source in cfg.sources:
        adapter = adapters.REGISTRY.get(source.type)
        if adapter is None:
            continue
        key = adapter.key(source)
        if isinstance(source, GithubSource):
            cache = adapter.cache_for(source, raw_dir(slug, source.type))
            out[key] = GithubBackend(cfg, source, cache, lookup)
        elif isinstance(source, LinearSource):
            out[key] = LinearBackend(cfg, source, lookup)
        elif isinstance(source, CanonicalJsonlSource):
            folder = cfg.resolve(source.path) / "archive"
            if folder.is_dir():
                out[key] = JsonlArchiveBackend(key, folder)
    return out
