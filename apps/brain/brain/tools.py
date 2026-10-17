"""Named query tools: the only way the CLI, the agents and the UI read the graph.

Why: answers must be deterministic and explainable, so there is no LLM-generated Cypher. Each
tool is one file in queries/tools/<name>.cypher plus, here, a pydantic model for its parameters
(what a caller may pass, with defaults and descriptions) and one for its result rows (always
with uids, and urls where the node has one, so every answer can cite its sources).

    TOOLS["experts_for_system"].params.model_json_schema()   # input schema for an agent tool
    call("falkordb", "experts_for_system", system="CI")      # -> list[Expert]
    experts_for_system("falkordb", system="CI")              # same, typed signature

`prepare` turns friendly parameters into query parameters (days -> epoch seconds, plain text ->
a RediSearch query or, for semantic search, the question's embedding, login -> person uid). It
never builds Cypher.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from brain import db
from brain.canonical import person_uid
from brain.embeddings import EmbeddingUnavailable, get_embedder

DAY = 86_400


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


# --- shared result pieces ---------------------------------------------------------------------


class Contributor(_Model):
    login: str
    changes: int


class ReviewerRef(_Model):
    login: str
    state: str | None = None


class ItemRef(_Model):
    uid: str
    number: int | None = None
    url: str | None = None


class LinkRef(_Model):
    uid: str
    number: int | None = None
    title: str | None = None
    url: str | None = None
    state: str | None = None


# --- tool rows and params ---------------------------------------------------------------------


class SystemParams(_Model):
    system: str = Field(description="Exact System name (see list_systems), e.g. 'CI'.")


class ExpertsParams(SystemParams):
    since_days: int | None = Field(None, description="Only count work from the last N days.")
    half_life_days: float = Field(90, description="Recency weight halves every N days.")
    review_weight: float = Field(0.5, description="A review counts this much of a commit.")
    limit: int = Field(10, ge=1, le=100)


class Expert(_Model):
    login: str
    person_uid: str
    score: float
    changes: int
    reviews: int
    last_active_ts: int | None
    teams: list[str]
    is_declared_owner: bool
    evidence: list[str]
    declared_owners: list[str]
    system_uid: str


class OwnersVsExpertsParams(_Model):
    since_days: int | None = Field(None, description="Only count work from the last N days.")
    top: int = Field(3, ge=1, le=10, description="How many top contributors to list.")


class OwnershipGap(_Model):
    system: str
    system_uid: str
    declared_owners: list[str]
    owner_people: list[str]
    members_known: bool
    top_contributors: list[Contributor]
    total_changes: int


class WorkHistoryParams(SystemParams):
    limit: int = Field(10, ge=1, le=100)


class WorkHistoryItem(_Model):
    uid: str
    kind: str
    number: int | None
    title: str
    state: str
    url: str | None
    created_at: str | None
    closed_at: str | None
    via: str
    author: str | None
    reviewers: list[ReviewerRef]
    closes: list[ItemRef]
    system_uid: str


class ImpactParams(SystemParams):
    limit: int = Field(5, ge=1, le=50)


class Impact(_Model):
    system: str
    system_uid: str
    co_changes: int
    coupling: float
    examples: list[str]
    people: list[Contributor]
    owners: list[str]


class PathParams(_Model):
    from_uid: str = Field(description="uid of the start node, e.g. 'person:erin'.")
    to_uid: str = Field(description="uid of the end node, e.g. 'system:Auth'.")
    max_len: int = Field(6, ge=1, le=10, description="Maximum hops.")
    paths: int = Field(3, ge=1, le=10, description="How many shortest paths to return.")


class PathNode(_Model):
    label: str
    uid: str
    name: str | None
    url: str | None


class PathRel(_Model):
    type: str
    from_: str = Field(alias="from")
    to: str


class Path(_Model):
    length: int
    nodes: list[PathNode]
    rels: list[PathRel]


class TextParams(_Model):
    text: str = Field(description="Plain words to search for, e.g. 'vector index crash'.")
    limit: int = Field(10, ge=1, le=50)


class RelatedWorkItem(_Model):
    uid: str
    kind: str
    number: int | None
    title: str
    state: str
    url: str | None
    score: float
    author: str | None
    systems: list[str]
    closes: list[ItemRef]
    closed_by: list[ItemRef]


class DocTextParams(TextParams):
    limit: int = Field(5, ge=1, le=50)


class RelatedDocument(_Model):
    uid: str
    title: str
    path: str
    url: str | None
    snippet: str
    score: float
    title_hits: int
    updated_at: str | None
    systems: list[str]
    mentions: list[ItemRef]


class SemanticParams(_Model):
    text: str = Field(description="The question in plain words, e.g. 'why do invoices fail'.")
    limit: int = Field(8, ge=1, le=30)
    kinds: list[Literal["comment", "work_item", "document"]] | None = Field(
        None, description="Only search these chunk kinds (default: all)."
    )


class SemanticHit(_Model):
    uid: str  # the WorkItem or Document the best chunk comes from: cite this, not the chunk
    label: str
    kind: str  # the WorkItem's kind (pull_request / issue / ticket / thread) or 'document'
    number: int | None
    title: str
    state: str | None
    url: str | None
    chunk_uid: str
    chunk_kind: str
    snippet: str
    similarity: float  # 0..1, higher is closer
    author: str | None
    systems: list[str]


class PersonParams(_Model):
    login: str = Field(description="Login / handle, e.g. 'erin' (case-insensitive).")
    limit: int = Field(5, ge=1, le=50, description="Max entries per list.")


class SystemActivity(_Model):
    system: str
    changes: int
    last_ts: int | None


class PersonProfile(_Model):
    login: str
    person_uid: str
    display_name: str | None
    is_bot: bool
    teams: list[str]
    systems: list[SystemActivity]
    prs_authored: int
    recent_prs: list[LinkRef]
    reviews_given: int
    recent_reviews: list[LinkRef]
    owns: list[str]


class WorkParams(PersonParams):
    limit: int = Field(20, ge=1, le=100, description="Max rows.")


class TicketRef(_Model):
    uid: str
    key: str | None = None
    title: str
    url: str | None = None
    status_category: str | None = None
    assignees: list[str]


class OpenWork(_Model):
    person_uid: str
    uid: str
    key: str | None
    title: str
    url: str | None
    state: str
    status_category: str | None
    priority: str | None
    due_date: str | None
    container: str | None
    blocked_by: list[TicketRef]
    blocks: list[TicketRef]


class Blocker(_Model):
    person_uid: str
    ticket: TicketRef
    blocker: TicketRef
    depth: int
    via: str | None  # key of the next ticket on the chain; None for a direct blocker
    linked: list[LinkRef]  # PRs and issues the blocker mentions


class Waiting(_Model):
    person_uid: str
    mine: TicketRef
    waiting: TicketRef


class EntityParams(_Model):
    uid: str = Field(description="uid of any node, e.g. 'github:FalkorDB/FalkorDB:pr:3063'.")
    limit: int = Field(25, ge=1, le=200, description="Max neighbours to return.")


class Neighbour(_Model):
    rel: str
    direction: str
    uid: str | None
    label: str
    title: str | None
    url: str | None


class Entity(_Model):
    uid: str
    label: str
    title: str | None
    kind: str | None
    state: str | None
    url: str | None
    date: str | None
    body: str
    neighbour_count: int
    neighbours: list[Neighbour]


class ListParams(_Model):
    limit: int = Field(100, ge=1, le=1000)


class SystemSummary(_Model):
    system: str
    system_uid: str
    path_rule: str | None
    changes: int
    people: int
    owners: list[str]


class RecentParams(_Model):
    limit: int = Field(10, ge=1, le=100)


class RecentWorkItem(_Model):
    uid: str
    kind: str
    number: int | None
    title: str
    state: str
    url: str | None
    author: str | None
    last_at: str | None  # latest of created / closed (ISO, as stored; a merged PR's closed_at)
    systems: list[str]


class PersonActivity(_Model):
    login: str
    person_uid: str
    display_name: str | None
    teams: list[str]
    prs: int
    reviews: int


class PersonRef(_Model):
    login: str
    person_uid: str


class CollaboratorsParams(_Model):
    login: str | None = Field(
        None, description="Only this person's pairs, e.g. 'erin' (default: everyone)."
    )
    since_days: int | None = Field(None, description="Only count reviews from the last N days.")
    limit: int = Field(10, ge=1, le=100)


class Collaborators(_Model):
    people: list[PersonRef]  # the pair; with a login, that person first
    reviews: int  # distinct PRs one of them reviewed of the other's
    a_reviewed_b: int  # PRs of people[1] that people[0] reviewed
    b_reviewed_a: int
    shared_threads: int  # issues, tickets and threads both commented on (not ranked)
    examples: list[LinkRef]  # latest reviewed PRs
    shared_examples: list[LinkRef]


class IssuesBySystemParams(_Model):
    state: Literal["open", "closed"] | None = Field(
        None, description="Only count issues in this state (default: both)."
    )
    limit: int = Field(10, ge=1, le=100)


class SystemIssues(_Model):
    system: str
    system_uid: str
    issues: int  # mentioned + fixed_in
    open: int
    closed: int
    mentioned: int  # issues whose text names a path in the system (the ranking)
    fixed_in: int  # other issues closed by a PR that changed the system
    examples: list[LinkRef]  # latest issues, mentioned first


class NoParams(_Model):
    pass


class NodeParams(_Model):
    uid: str = Field(description="uid of any node, e.g. 'system:Auth' or 'person:erin'.")


class EvidenceRef(_Model):
    uid: str
    label: str
    title: str | None = None
    url: str | None = None


class KeeperNote(_Model):
    uid: str
    kind: str
    statement: str
    value: str | None
    valid_from: str | None
    approved_by: str | None
    evidence: list[EvidenceRef]


class Stat(_Model):
    kind: str
    type: str
    count: int


# --- parameter preparation --------------------------------------------------------------------


def since_ts(days: int | None, now: int | None = None) -> int:
    """Epoch seconds `days` days before `now` (default: the clock); 0 (all time) without days."""
    if not days:
        return 0
    return (int(time.time()) if now is None else now) - days * DAY


def _since(p: dict[str, Any]) -> dict[str, Any]:
    days = p.pop("since_days", None)
    now = int(time.time())
    return {**p, "now": now, "since_ts": since_ts(days, now)}


def fulltext_query(text: str) -> str:
    """Plain text -> RediSearch query: words OR-ed, so any word matches and more is better.

    Only word characters survive, so user text can never inject RediSearch syntax.
    """
    words = dict.fromkeys(w.lower() for w in re.findall(r"\w+", text) if len(w) > 2)
    return "|".join(words)


def _text(p: dict[str, Any]) -> dict[str, Any] | None:
    """None when the text has no usable words: nothing to search."""
    query = fulltext_query(p["text"])
    if not query:
        return None
    return {"query": query, "words": query.split("|"), "limit": p["limit"]}


SEMANTIC_OFF = (
    "Semantic search is off: set EMBEDDING_PROVIDER=fastembed (or gemini) and run make embed."
)
SEMANTIC_MAX_K = 200


def _semantic(p: dict[str, Any]) -> dict[str, Any] | None:
    """Embed the question. Blank text gives None (no search) without touching the model.
    The kinds filter runs after the nearest-neighbour step, so with kinds set the query fetches
    the most chunks it may, or comments could crowd out every document. No kinds (or an empty
    list) means every kind."""
    if not p["text"].strip():
        return None
    kinds = p["kinds"] or None
    k = SEMANTIC_MAX_K if kinds else min(p["limit"] * 4, SEMANTIC_MAX_K)
    embedder = get_embedder()
    if embedder is None:
        raise EmbeddingUnavailable(SEMANTIC_OFF)
    return {
        "vector": embedder.query(p["text"]),
        "k": k,
        "limit": p["limit"],
        "kinds": kinds,
        "model": embedder.model,
    }


def _no_semantic_hits(slug: str, model: str) -> None:
    """A semantic search found nothing: raise when that is because the graph has no vectors
    from `model` (none at all, or another model's), so the agent hears why instead of reading
    "nothing matched". Returns when vectors from `model` are there (the filters left nothing)."""
    models = {r["model"]: r["n"] for r in db.run(slug, "load/embedded_models", read_only=True)}
    if model in models:
        return
    if not models:
        raise EmbeddingUnavailable(
            f"Nothing in this company's graph is embedded yet, so semantic search finds nothing. "
            f"Run make embed SLUG={slug}."
        )
    others = ", ".join(str(m) for m in models)
    raise EmbeddingUnavailable(
        f"This company's text was embedded with {others}, not {model}, so semantic search "
        f"cannot compare it with the question. Run make embed SLUG={slug} to embed it again."
    )


def _person(p: dict[str, Any]) -> dict[str, Any]:
    return {"person_uid": person_uid(p["login"]), "limit": p["limit"]}


def _pairs(p: dict[str, Any]) -> dict[str, Any]:
    login = p.pop("login", None)
    return {**_since(p), "person_uid": person_uid(login) if login else None}


# --- registry ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Tool:
    name: str
    description: str  # one sentence, written for an LLM choosing a tool
    params: type[_Model]
    row: type[_Model]
    # query params from the validated params; None means nothing to search (no rows)
    prepare: Callable[[dict[str, Any]], dict[str, Any] | None] = lambda p: p
    # run when the query returns no rows, with the query params (e.g. to raise why)
    on_empty: Callable[[str, dict[str, Any]], None] | None = None

    @property
    def query(self) -> str:
        return f"tools/{self.name}"


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "experts_for_system",
            "People who know a system best, from recent commits and reviews, with its "
            "declared owners.",
            ExpertsParams,
            Expert,
            _since,
        ),
        Tool(
            "owners_vs_experts",
            "Systems whose declared owners (CODEOWNERS) are not the people doing the work.",
            OwnersVsExpertsParams,
            OwnershipGap,
            _since,
        ),
        Tool(
            "work_history",
            "Recent PRs and issues that changed or mention a system, with authors and reviewers.",
            WorkHistoryParams,
            WorkHistoryItem,
        ),
        Tool(
            "impact_of",
            "Systems usually changed together with a system, and who works on them.",
            ImpactParams,
            Impact,
        ),
        Tool(
            "path_between",
            "Shortest chains of relationships connecting two nodes, to explain a connection.",
            PathParams,
            Path,
        ),
        Tool(
            "related_work_items",
            "PRs, issues and threads about a topic (full-text search), with systems and links.",
            TextParams,
            RelatedWorkItem,
            _text,
        ),
        Tool(
            "related_documents",
            "Design docs, ADRs and READMEs about a topic (full-text search).",
            DocTextParams,
            RelatedDocument,
            _text,
        ),
        Tool(
            "semantic_search",
            "Work items and documents whose text means the same as the question, even in other "
            "words (semantic search). Use for why/how questions; use related_work_items for "
            "exact names, numbers and keys.",
            SemanticParams,
            SemanticHit,
            _semantic,
            on_empty=lambda slug, p: _no_semantic_hits(slug, p["model"]),
        ),
        Tool(
            "person_profile",
            "One person's teams, systems, recent PRs, reviews and declared ownership.",
            PersonParams,
            PersonProfile,
            _person,
        ),
        Tool(
            "open_work_for",
            "Open tickets assigned to a person, most urgent first, with what blocks them and "
            "what they block.",
            WorkParams,
            OpenWork,
            _person,
        ),
        Tool(
            "blocked_on",
            "What a person's open tickets are waiting on: open blockers up to three steps away, "
            "who owns each, and linked PRs.",
            WorkParams,
            Blocker,
            _person,
        ),
        Tool(
            "waiting_on",
            "Other people's open tickets that are blocked by a person's open tickets.",
            WorkParams,
            Waiting,
            _person,
        ),
        Tool(
            "get_entity",
            "Open any node by uid: its fields, text and direct neighbours.",
            EntityParams,
            Entity,
        ),
        Tool(
            "list_systems",
            "All systems (code areas) with change counts, people and owners.",
            ListParams,
            SystemSummary,
        ),
        Tool(
            "recent_work_items",
            "Most recent PRs, issues and threads, newest first.",
            RecentParams,
            RecentWorkItem,
        ),
        Tool(
            "people_activity",
            "People with how many PRs they authored and reviewed.",
            ListParams,
            PersonActivity,
        ),
        Tool(
            "collaborators",
            "Who works most closely together: pairs of people ranked by PRs one reviewed of "
            "the other's, with example PRs. Give a login for that person's closest "
            "collaborators.",
            CollaboratorsParams,
            Collaborators,
            _pairs,
        ),
        Tool(
            "issues_by_system",
            "Which systems (modules, code areas) have the most issues: open and closed issue "
            "counts per system, ranked, with example issues.",
            IssuesBySystemParams,
            SystemIssues,
        ),
        Tool("graph_stats", "Node and relationship counts in the company graph.", NoParams, Stat),
        Tool(
            "keeper_notes",
            "Keeper notes about a node: accepted claims the sources don't state, with their "
            "evidence.",
            NodeParams,
            KeeperNote,
        ),
    ]
}


def call(slug: str, name: str, **params: Any) -> list[_Model]:
    """Validate params, run the named read-only query on brain_<slug>, return typed rows."""
    tool = TOOLS.get(name)
    if tool is None:
        raise KeyError(f"unknown tool {name!r}; known: {', '.join(sorted(TOOLS))}")
    query_params = tool.prepare(tool.params.model_validate(params).model_dump())
    if query_params is None:  # nothing to search (no usable words, a blank question)
        return []
    rows = db.run(slug, tool.query, query_params, read_only=True)
    if not rows and tool.on_empty:
        tool.on_empty(slug, query_params)
    return [tool.row.model_validate(_plain(r)) for r in rows]


def _plain(value: Any) -> Any:
    """FalkorDB returns maps as OrderedDicts; make nested values plain dicts/lists."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


# --- typed wrappers ---------------------------------------------------------------------------


def experts_for_system(
    slug: str, system: str, since_days: int | None = None, limit: int = 10
) -> list[Expert]:
    return call(slug, "experts_for_system", system=system, since_days=since_days, limit=limit)


def owners_vs_experts(slug: str, since_days: int | None = None) -> list[OwnershipGap]:
    return call(slug, "owners_vs_experts", since_days=since_days)


def work_history(slug: str, system: str, limit: int = 10) -> list[WorkHistoryItem]:
    return call(slug, "work_history", system=system, limit=limit)


def impact_of(slug: str, system: str, limit: int = 5) -> list[Impact]:
    return call(slug, "impact_of", system=system, limit=limit)


def path_between(slug: str, from_uid: str, to_uid: str, max_len: int = 6) -> list[Path]:
    return call(slug, "path_between", from_uid=from_uid, to_uid=to_uid, max_len=max_len)


def related_work_items(slug: str, text: str, limit: int = 10) -> list[RelatedWorkItem]:
    return call(slug, "related_work_items", text=text, limit=limit)


def related_documents(slug: str, text: str, limit: int = 5) -> list[RelatedDocument]:
    return call(slug, "related_documents", text=text, limit=limit)


def semantic_search(
    slug: str, text: str, limit: int = 8, kinds: list[str] | None = None
) -> list[SemanticHit]:
    return call(slug, "semantic_search", text=text, limit=limit, kinds=kinds)


def person_profile(slug: str, login: str) -> PersonProfile | None:
    rows = call(slug, "person_profile", login=login)
    return rows[0] if rows else None


def open_work_for(slug: str, login: str, limit: int = 20) -> list[OpenWork]:
    return call(slug, "open_work_for", login=login, limit=limit)


def blocked_on(slug: str, login: str, limit: int = 20) -> list[Blocker]:
    return call(slug, "blocked_on", login=login, limit=limit)


def waiting_on(slug: str, login: str, limit: int = 20) -> list[Waiting]:
    return call(slug, "waiting_on", login=login, limit=limit)


def get_entity(slug: str, uid: str, limit: int = 25) -> Entity | None:
    rows = call(slug, "get_entity", uid=uid, limit=limit)
    return rows[0] if rows else None


def list_systems(slug: str, limit: int = 100) -> list[SystemSummary]:
    return call(slug, "list_systems", limit=limit)


def recent_work_items(slug: str, limit: int = 10) -> list[RecentWorkItem]:
    return call(slug, "recent_work_items", limit=limit)


def people_activity(slug: str, limit: int = 100) -> list[PersonActivity]:
    return call(slug, "people_activity", limit=limit)


def collaborators(
    slug: str, login: str | None = None, since_days: int | None = None, limit: int = 10
) -> list[Collaborators]:
    return call(slug, "collaborators", login=login, since_days=since_days, limit=limit)


def issues_by_system(slug: str, state: str | None = None, limit: int = 10) -> list[SystemIssues]:
    return call(slug, "issues_by_system", state=state, limit=limit)


def graph_stats(slug: str) -> list[Stat]:
    return call(slug, "graph_stats")


def keeper_notes(slug: str, uid: str) -> list[KeeperNote]:
    return call(slug, "keeper_notes", uid=uid)
