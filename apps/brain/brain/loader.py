"""Write canonical records into a company graph.

Why: this is the only code that writes ingested data to FalkorDB, and it knows nothing about
where records came from. For each record type it builds plain dict rows and runs the matching
queries/load/*.cypher file in batches (`UNWIND $rows AS row`, 500 rows per query).

Every write is `MERGE` on uid followed by `SET`, so loading the same records twice changes
nothing, and loading an updated record updates the node in place.

Write order matters: nodes first, then the relationships between them. Relationship queries
MATCH both ends, so a link to something that is not in the graph is dropped (and counted).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from brain import db
from brain.canonical import (
    URL_PREFIX,
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
    is_url_ref,
    person_uid,
    system_uid,
    team_uid,
    to_utc,
)
from brain.chunking import split_text, text_hash

BATCH_SIZE = 500

# (rel, from_label, to_label) -> load query. Mirrors canonical.ALLOWED_LINKS.
LINK_QUERIES: dict[tuple[str, str, str], str] = {
    ("CLOSES", "WorkItem", "WorkItem"): "load/link_closes",
    ("PART_OF", "Change", "WorkItem"): "load/link_part_of",
    ("MEMBER_OF", "Person", "Team"): "load/link_member_of",
    ("MENTIONS", "WorkItem", "WorkItem"): "load/link_mentions_workitem_workitem",
    ("MENTIONS", "WorkItem", "System"): "load/link_mentions_workitem_system",
    ("MENTIONS", "Document", "WorkItem"): "load/link_mentions_document_workitem",
    ("MENTIONS", "Document", "System"): "load/link_mentions_document_system",
    ("BLOCKS", "WorkItem", "WorkItem"): "load/link_blocks",
}

# Same, for a link whose to_uid is a url ref (the target is the work item with that url).
# Mirrors canonical.URL_LINKS.
URL_LINK_QUERIES: dict[tuple[str, str, str], str] = {
    ("MENTIONS", "WorkItem", "WorkItem"): "load/link_mentions_workitem_workitem_by_url",
}

# For sorting tickets by priority; no priority sorts last.
PRIORITY_RANK = {"urgent": 1, "high": 2, "medium": 3, "low": 4}
NO_PRIORITY_RANK = 5


@dataclass
class LoadReport:
    written: dict[str, int] = field(default_factory=lambda: defaultdict(int))  # query -> rows
    dropped: dict[str, int] = field(default_factory=lambda: defaultdict(int))  # query -> rows
    superseded: dict[str, str] = field(default_factory=dict)  # archived uid -> newer uid marked

    def merge(self, other: LoadReport) -> None:
        for k, v in other.written.items():
            self.written[k] += v
        for k, v in other.dropped.items():
            self.dropped[k] += v
        self.superseded.update(other.superseded)


# --- value helpers ----------------------------------------------------------------------------


def iso(dt: datetime | None) -> str | None:
    dt = to_utc(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def epoch(dt: datetime | None) -> int | None:
    dt = to_utc(dt)
    return int(dt.timestamp()) if dt else None


def day_epoch(d: date | None) -> int | None:
    """The date at 00:00 UTC, in epoch seconds."""
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp()) if d else None


def _priority_rank(w: WorkItem) -> int | None:
    """Sort rank for tickets (anything with a status category); None for PRs and issues."""
    if w.status_category is None:
        return None
    return PRIORITY_RANK.get(w.priority or "", NO_PRIORITY_RANK)


def _titled(title: str, body: str) -> str:
    """The text a work item or document is searched by: its title, then its body."""
    return f"{title}\n\n{body}" if body.strip() else title


def _base(r: CanonicalRecord) -> dict[str, Any]:
    return {"uid": r.uid, "source": r.source, "url": r.url}


# --- runner -----------------------------------------------------------------------------------


def _n(result: list[dict[str, Any]]) -> int:
    """The `n` a write query returns (rows written), 0 when it returns nothing."""
    return result[0]["n"] if result else 0


def _batches(
    slug: str, query: str, rows: list[dict[str, Any]], params: dict[str, Any]
) -> Iterator[tuple[int, int]]:
    """Run `query` on `rows` in batches of BATCH_SIZE (as $rows, beside `params`); yield
    (rows sent, rows written) per batch. No rows: no query."""
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        yield len(batch), _n(db.run(slug, query, {**params, "rows": batch}))


def _run(slug: str, query: str, rows: list[dict[str, Any]], report: LoadReport) -> None:
    for sent, n in _batches(slug, query, rows, {"company": slug}):
        report.written[query] += n
        report.dropped[query] += sent - n


def _dedupe(records: Iterable[CanonicalRecord]) -> dict[type, list[CanonicalRecord]]:
    """Group by type; for the same uid, the last record wins."""
    by_type: dict[type, dict[str, CanonicalRecord]] = defaultdict(dict)
    for r in records:
        by_type[type(r)][r.uid] = r
    return {t: list(d.values()) for t, d in by_type.items()}


def load(slug: str, records: Iterable[CanonicalRecord], origin: str | None = None) -> LoadReport:
    """Write records to brain_<slug>. Idempotent.

    `origin` is the key of the source being loaded. With it, the BLOCKS edges of that source that
    this load did not write are deleted afterwards: the load is that source's whole picture of
    its dependencies. Without it nothing is ever pruned.
    """
    groups = _dedupe(records)
    rep = LoadReport()

    def of(t: type) -> list:
        return groups.get(t, [])

    # 1. nodes
    _run(
        slug,
        "load/person",
        [
            {**_base(p), "login": p.login, "display_name": p.display_name, "is_bot": p.is_bot}
            for p in of(Person)
        ],
        rep,
    )
    _run(slug, "load/team", [{**_base(t), "name": t.name} for t in of(Team)], rep)
    _run(
        slug,
        "load/system",
        [{**_base(s), "name": s.name, "path_rule": s.path_rule} for s in of(System)],
        rep,
    )
    _run(
        slug,
        "load/work_item",
        [
            {
                **_base(w),
                "kind": w.kind,
                "number": w.number,
                "title": w.title,
                "body": w.body,
                "state": w.state,
                "created_at": iso(w.created_at),
                "created_ts": epoch(w.created_at),
                "updated_at": iso(w.updated_at),
                "closed_at": iso(w.closed_at),
                "closed_ts": epoch(w.closed_at),
                "merged_at": iso(w.merged_at),
                "labels": w.labels,
                "container": w.container,
                "key": w.key,
                "status_category": w.status_category,
                "priority": w.priority,
                "priority_rank": _priority_rank(w),
                "due_date": w.due_date.isoformat() if w.due_date else None,
                "due_ts": day_epoch(w.due_date),
                "unresolved_refs": w.unresolved_refs,
            }
            for w in of(WorkItem)
        ],
        rep,
    )
    _run(
        slug,
        "load/document",
        [
            {
                **_base(d),
                "path": d.path,
                "title": d.title,
                "body": d.body,
                "updated_at": iso(d.updated_at),
            }
            for d in of(Document)
        ],
        rep,
    )
    _load_body_chunks(slug, of(WorkItem), of(Document), rep)
    _run(
        slug,
        "load/change",
        [
            {
                **_base(c),
                "sha": c.sha,
                "date": iso(c.date),
                "ts": epoch(c.date),
                "kind": c.kind or "other",
                "subject": c.subject,
            }
            for c in of(Change)
        ],
        rep,
    )

    # 2. authorship
    for t, query in [
        (Change, "load/authored_change"),
        (WorkItem, "load/authored_work_item"),
        (Document, "load/authored_document"),
    ]:
        _run(
            slug,
            query,
            [
                {"person_uid": person_uid(r.author_login), "target_uid": r.uid}
                for r in of(t)
                if r.author_login
            ],
            rep,
        )

    # assignees are replaced, not accumulated; only for items whose source tracks them
    _run(
        slug,
        "load/assigned_to",
        [
            {
                "work_item_uid": w.uid,
                "person_uids": [person_uid(a) for a in w.assignees],
                "source": w.source,
            }
            for w in of(WorkItem)
            if w.assignees is not None
        ],
        rep,
    )

    # 3. other relationships
    _run(
        slug,
        "load/touches",
        [
            {"change_uid": c.uid, "system_uid": system_uid(name), "files": files}
            for c in of(Change)
            for name, files in c.touches.items()
        ],
        rep,
    )
    reviews = sorted(of(Review), key=lambda r: epoch(r.submitted_at) or 0)
    _run(
        slug,
        "load/reviewed",
        [
            {
                "person_uid": person_uid(r.reviewer_login),
                "work_item_uid": r.work_item_uid,
                "state": r.state,
                "submitted_at": iso(r.submitted_at),
                "ts": epoch(r.submitted_at),
            }
            for r in reviews
        ],
        rep,
    )
    comments: list[Comment] = of(Comment)
    _write_comment_chunks(
        slug,
        [
            {
                **_base(c),
                "comment_uid": c.uid,
                "work_item_uid": c.work_item_uid,
                "author_uid": person_uid(c.author_login),
                "text": c.body,
                "created_at": iso(c.created_at),
                "ts": epoch(c.created_at),
            }
            for c in comments
        ],
        rep,
    )
    pairs = sorted({(person_uid(c.author_login), c.work_item_uid) for c in comments})
    _run(slug, "load/commented_on", [{"person_uid": p, "work_item_uid": w} for p, w in pairs], rep)
    _load_ownership(slug, of(Ownership), rep)
    links: dict[str, list[dict[str, Any]]] = defaultdict(list)
    kept_blocks: list[str] = []
    for link in of(Link):
        key = (link.rel, link.from_label, link.to_label)
        row: dict[str, Any] = {"from_uid": link.from_uid, "source": link.source}
        if is_url_ref(link.to_uid):
            query = URL_LINK_QUERIES[key]
            row["to_url"] = link.to_uid.removeprefix(URL_PREFIX)
        else:
            query = LINK_QUERIES[key]
            row["to_uid"] = link.to_uid
        if link.rel == "BLOCKS":
            row.update(origin=origin, uid=link.uid)
            kept_blocks.append(link.uid)
        links[query].append(row)
    for query, rows in links.items():
        _run(slug, query, rows, rep)
    if origin is not None:
        # not a row batch, so it is not counted in the report
        db.run(slug, "load/prune_blocks", {"origin": origin, "keep": kept_blocks})
    return rep


def _pieces(first_uid: str, text: str, row: dict[str, Any]) -> list[dict[str, Any]]:
    """Chunk rows for `text` cut by `split_text`, each a copy of `row`. Piece 0 keeps
    `first_uid`, the uid the whole text had before long text was cut, so a short text's chunk
    and its vector stay as they were; piece i is `<first_uid>:<i>`. A blank text keeps one
    empty chunk, so a blank comment is still counted."""
    texts = split_text(text) or [text]
    return [
        {
            **row,
            "uid": first_uid if i == 0 else f"{first_uid}:{i}",
            "idx": i,
            "text": t,
            "text_hash": text_hash(t),
        }
        for i, t in enumerate(texts)
    ]


def _write_body_chunks(slug: str, items: list[dict[str, Any]], rep: LoadReport) -> None:
    """Write the chunks of work-item texts: {uid (the work item), title, body, created_at, ts,
    source, url}. A text now cut into fewer pieces loses the extra chunks."""
    rows, prune = [], []
    for w in items:
        base = {k: w[k] for k in ("created_at", "ts", "source", "url")}
        pieces = _pieces(
            f"chunk:{w['uid']}:body",
            _titled(w["title"], w["body"] or ""),
            {**base, "work_item_uid": w["uid"]},
        )
        rows += pieces
        prune.append({"work_item_uid": w["uid"], "keep": len(pieces)})
    _run(slug, "load/work_item_chunk", rows, rep)
    _run(slug, "load/prune_work_item_chunks", prune, rep)


def _write_comment_chunks(slug: str, comments: list[dict[str, Any]], rep: LoadReport) -> None:
    """Write the chunks of comments: {comment_uid, work_item_uid, author_uid, text, created_at,
    ts, source, url}. A comment now cut into fewer pieces loses the extra chunks."""
    rows, prune = [], []
    for c in comments:
        pieces = _pieces(f"chunk:{c['comment_uid']}", c["text"], c)
        rows += pieces
        prune.append(
            {
                "work_item_uid": c["work_item_uid"],
                "comment_uid": c["comment_uid"],
                "keep": len(pieces),
            }
        )
    _run(slug, "load/comment_chunk", rows, rep)
    _run(slug, "load/prune_comment_chunks", prune, rep)


def _load_body_chunks(
    slug: str, items: list[WorkItem], docs: list[Document], rep: LoadReport
) -> None:
    """Chunks for the text of work items and documents, both cut by `split_text`.

    Only the records of this load are written, so an incremental ingest touches only what
    changed. A text that now has fewer chunks loses the extra ones.
    """
    _write_body_chunks(
        slug,
        [
            {
                **_base(w),
                "title": w.title,
                "body": w.body,
                "created_at": iso(w.created_at),
                "ts": epoch(w.created_at),
            }
            for w in items
        ],
        rep,
    )

    doc_rows = []
    prune_rows = []
    for d in docs:
        texts = split_text(_titled(d.title, d.body))
        prune_rows.append({"doc_uid": d.uid, "keep": len(texts)})
        for i, text in enumerate(texts):
            doc_rows.append(
                {
                    **_base(d),
                    "uid": f"chunk:{d.uid}:{i}",
                    "document_uid": d.uid,
                    "idx": i,
                    "text": text,
                    "text_hash": text_hash(text),
                    "ts": epoch(d.updated_at),
                }
            )
    _run(slug, "load/document_chunk", doc_rows, rep)
    _run(slug, "load/prune_document_chunks", prune_rows, rep)


def backfill_chunks(slug: str) -> int:
    """Cut the text of graphs built before it was cut: give every work item that has no body
    chunk its chunks, and split each body or comment chunk written whole (it has no idx). An
    incremental ingest never reloads old items, so they would stay as they are. Chunks are
    written exactly as a load writes them; a short text's chunk keeps its text and hash, so it
    is not embedded again. Returns the texts written (0 when nothing was left to do)."""
    rep = LoadReport()
    items = db.run(slug, "load/unsplit_bodies", read_only=True)
    _write_body_chunks(slug, items, rep)
    comments = db.run(slug, "load/unsplit_comments", read_only=True)
    _write_comment_chunks(slug, comments, rep)
    return len(items) + len(comments)


def _load_ownership(slug: str, owns: list[Ownership], rep: LoadReport) -> None:
    """One OWNS edge per (owner, system); several patterns for the same pair are joined."""
    # kind -> (owner uid, system uid) -> (patterns, source); the last record's source wins
    edges: dict[str, dict[tuple[str, str], tuple[list[str], str]]] = {"team": {}, "person": {}}
    for o in owns:
        owner = person_uid(o.owner) if o.owner_kind == "person" else team_uid(o.owner)
        pairs = edges[o.owner_kind]
        for name in o.systems:
            pair = (owner, system_uid(name))
            pats = pairs[pair][0] if pair in pairs else []
            pats.append(o.pattern)
            pairs[pair] = (pats, o.source)
    for kind, pairs in edges.items():
        _run(
            slug,
            f"load/owns_{kind}",
            [
                {"owner_uid": owner, "system_uid": sys, "pattern": ", ".join(pats), "source": src}
                for (owner, sys), (pats, src) in pairs.items()
            ],
            rep,
        )


# --- embeddings -------------------------------------------------------------------------------


def chunks_to_embed(
    slug: str, model: str, limit: int, sources: list[str] | None = None
) -> list[dict[str, Any]]:
    """The next `limit` chunks (uid, text, text_hash) not yet embedded from their current text
    by `model`, by uid. Chunks with no text are never returned. `sources` limits them to the
    chunks of those work items or documents."""
    params: dict[str, Any] = {"model": model, "limit": limit}
    if sources is None:
        return db.run(slug, "load/chunks_to_embed", params, read_only=True)
    return db.run(slug, "load/chunks_to_embed_from", {**params, "sources": sources}, read_only=True)


def set_embeddings(slug: str, rows: list[dict[str, Any]], model: str) -> int:
    """Store vectors: rows of {uid, vector, text_hash}. Returns the chunks written."""
    return sum(n for _, n in _batches(slug, "load/chunk_embedding", rows, {"model": model}))


def clear_embedded(slug: str) -> int:
    """Mark every chunk as pending for the embed stage. Returns the chunks marked."""
    return _n(db.run(slug, "load/clear_embedded"))


# --- archive (items older than the ingest window, loaded on demand) -------------------------


def mark_archived(slug: str, rows: list[dict[str, Any]]) -> int:
    """Flag loaded nodes as archived: rows of {uid, ref, archived_at, request}. Returns the
    nodes marked (WorkItem or Document; a uid that is not in the graph marks nothing)."""
    return sum(n for _, n in _batches(slug, "load/archive_mark", rows, {}))


def resolve_refs(slug: str) -> int:
    """Link every item's unresolved ref to the archived node carrying that `ref` (MENTIONS) and
    drop the ref from the item. Returns the edges made; a second call makes none."""
    return sum(row["n"] for row in db.run(slug, "load/archive_resolve"))  # one row per kind


def mark_superseded(slug: str, uid: str, by_uid: str) -> bool:
    """Record that `by_uid` supersedes `uid` (SUPERSEDED_BY edge + `superseded_by` property).
    False when either node is missing."""
    return _n(db.run(slug, "load/archive_supersede", {"uid": uid, "by_uid": by_uid})) > 0


# --- sync state -------------------------------------------------------------------------------


def get_cursor(slug: str, key: str, window_since: str) -> datetime | None:
    """The source's ingest cursor, or None (= load everything) if there is none yet or the
    config window changed since the last ingest (widening it must pull in older records)."""
    rows = db.run(slug, "load/sync_state_get", {"uid": f"sync:{key}"}, read_only=True)
    if not rows or not rows[0]["cursor"] or rows[0]["window_since"] != window_since:
        return None
    return datetime.fromisoformat(rows[0]["cursor"])


def set_sync_state(
    slug: str, adapter: str, key: str, cursor: datetime | None, window_since: str, records: int
) -> None:
    db.run(
        slug,
        "load/sync_state_set",
        {
            "company": slug,
            "uid": f"sync:{key}",
            "adapter": adapter,
            "key": key,
            "cursor": iso(cursor),
            "window_since": window_since,
            "last_run": iso(datetime.now(UTC)),
            "records": records,
        },
    )
