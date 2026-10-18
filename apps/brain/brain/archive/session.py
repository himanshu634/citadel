"""One Archivist request's access to the sources, with its budgets.

Why: the model chooses what to search and fetch; the budgets are code. A session counts every
external call (a search or a fetch, whatever the retries inside it) against `Budget.calls`,
refuses a fetch that is more than `Budget.depth` hops of refs away from where the request
started, and loads at most `Budget.items` items, and never past the company's daily cap
(`archivist_daily_cap` items archived per UTC day, counted from the archive cache). A spent
budget raises `BudgetSpent` naming it, before any call is made. Brain lookups are free.

`load` writes each chosen item to the archive cache (so rebuilds bring it back) and loads those
entries only, through the same `pipeline.load_entries` a build uses; new chunks are embedded at
once (those only, not the company's backlog) when the embedding model is already loaded (never
load it on the Ask path).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal

from brain import embeddings, loader, pipeline
from brain.archive.backends import (
    MAX_RESULTS,
    Backend,
    Candidate,
    Fetched,
    OutOfScope,
    backends_for,
    lookup_node,
)
from brain.archive.cache import ArchiveEntry, read_entries, write_entry
from brain.config import get_settings, load_company


@dataclass(frozen=True)
class Budget:
    calls: int  # external calls (search + fetch)
    items: int  # items loaded
    depth: int  # hops of refs from the request's own items

    @classmethod
    def for_tier(cls, tier: Literal["ask", "keeper"]) -> Budget:
        s = get_settings()
        if tier == "ask":
            return cls(s.archivist_calls_ask, s.archivist_items_ask, s.archivist_depth)
        return cls(s.archivist_calls_keeper, s.archivist_items_keeper, s.archivist_depth)


class BudgetSpent(Exception):
    """A budget is spent. `budget` names it: calls, items, depth or daily_cap."""

    def __init__(self, budget: str, detail: str) -> None:
        self.budget = budget
        super().__init__(f"The {budget} budget is spent: {detail}.")


def _utc_day(iso: str) -> date | None:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(UTC).date()
    except ValueError:
        return None


def daily_loaded(slug: str, day: date) -> int:
    """Items archived for the company on that UTC day (from the cache's `archived_at`)."""
    return sum(1 for e in read_entries(slug) if _utc_day(e.archived_at) == day)


class ArchiveSession:
    def __init__(
        self,
        slug: str,
        budget: Budget,
        *,
        backends: dict[str, Backend] | None = None,
        now: Callable[[], datetime] | None = None,
        start_refs: list[str] | None = None,
    ) -> None:
        self.slug = slug
        self.budget = budget
        self.cfg = load_company(slug)
        self.backends = backends if backends is not None else backends_for(slug)
        self._now = now or (lambda: datetime.now(UTC))
        self.calls_used = 0
        self.fetched: dict[str, Fetched] = {}  # by uid
        self.depth: dict[str, int] = {}  # uid -> hops from the request's own items
        self.loaded: list[str] = []
        self.superseded: dict[str, str] = {}  # archived uid -> newer uid, as marked
        self.start_refs = list(start_refs or [])  # the request's own refs: depth 0
        self._by_id: dict[tuple[str, str], Fetched] = {}  # (source key, item id) -> fetched

    def close(self) -> None:
        for b in self.backends.values():
            if close := getattr(b, "close", None):
                close()

    def backend(self, source_key: str) -> Backend:
        try:
            return self.backends[source_key]
        except KeyError:
            known = ", ".join(sorted(self.backends)) or "none"
            raise OutOfScope(
                f"{source_key} is not an archive source of this company (sources: {known})."
            ) from None

    def lookup(self, ref: str) -> dict[str, Any] | None:
        """The brain node `ref` points at (a uid, url, "#812", key ...), or None. Free."""
        if node := lookup_node(self.slug, {"uid": ref.strip(), "url": ref.strip()}):
            return node
        for b in self.backends.values():
            if (item := b.parse_ref(ref)) and (node := lookup_node(self.slug, b.match(item))):
                return node
        return None

    def _spend(self) -> None:
        if self.calls_used >= self.budget.calls:
            raise BudgetSpent("calls", f"{self.calls_used} of {self.budget.calls} calls used")
        self.calls_used += 1

    def search(self, source_key: str, terms: str) -> list[Candidate]:
        b = self.backend(source_key)
        self._spend()
        return b.search(terms, self.cfg.window.since)[:MAX_RESULTS]

    @staticmethod
    def _names(b: Backend, refs: list[str], ids: set[str]) -> bool:
        """Whether any of `refs` names one of `ids` (as written, or parsed by the backend)."""
        return any(r in ids or b.parse_ref(r) in ids for r in refs)

    def _depth_of(self, b: Backend, ids: set[str]) -> int | None:
        """0 for one of the request's own refs; else 1 + the depth of the shallowest fetched
        item whose refs name it; None when nothing does (it starts a trail, e.g. a search hit).
        `ids` are every id known for the item, so an alias (a key, "#812") is not a fresh start
        once the fetch has told its uid."""
        if self._names(b, self.start_refs, ids):
            return 0
        parents = [self.depth[u] for u, f in self.fetched.items() if self._names(b, f.refs, ids)]
        return 1 + min(parents) if parents else None

    def _too_deep(self, item_id: str, depth: int | None) -> None:
        if depth is not None and depth > self.budget.depth:
            raise BudgetSpent(
                "depth", f"{item_id} is {depth} hops away, the limit is {self.budget.depth}"
            )

    def fetch(self, source_key: str, item_id: str) -> Fetched:
        b = self.backend(source_key)
        target = b.parse_ref(item_id) or item_id
        for key in (item_id, target):
            if hit := self._by_id.get((source_key, key)):
                return hit
        self._too_deep(item_id, self._depth_of(b, {item_id, target}))
        self._spend()
        got = b.fetch(target)
        uid = got.candidate.uid
        if uid in self.fetched:  # the same item asked for by another id (a key, then its uid)
            got = self.fetched[uid]
        else:
            # Its uid may name a parent's ref that the alias did not: the call is spent, but an
            # item past the depth budget is never kept (so never loaded).
            ids = {item_id, target, uid, got.candidate.id, got.candidate.ref}
            depth = self._depth_of(b, ids)
            self._too_deep(item_id, depth)
            self.fetched[uid] = got
            self.depth[uid] = depth or 0
        for key in (item_id, target, got.candidate.id):
            self._by_id[(source_key, key)] = got
        return got

    def load(
        self, request: str, uids: list[str], *, superseded: dict[str, str] | None = None
    ) -> list[str]:
        """Archive and load fetched items (in order, up to the item budget and the daily cap);
        returns the uids loaded. `superseded` maps an older uid to the uid that replaces it; a
        pair applies only when its older item is loaded now, and is kept in its cache entry so a
        rebuild marks it again. The pairs marked are added to `self.superseded`."""
        if unknown := [u for u in uids if u not in self.fetched]:
            raise ValueError(f"not fetched in this session: {', '.join(unknown)}")
        wanted = [u for u in dict.fromkeys(uids) if u not in self.loaded]
        now = self._now().astimezone(UTC)
        room_items = self.budget.items - len(self.loaded)
        cap = get_settings().archivist_daily_cap
        room_day = cap - daily_loaded(self.slug, now.date())
        if wanted and room_items <= 0:
            raise BudgetSpent("items", f"{len(self.loaded)} of {self.budget.items} items loaded")
        if wanted and room_day <= 0:
            raise BudgetSpent("daily_cap", f"{cap} items were archived today")
        take = wanted[: min(room_items, room_day)]
        entries = []
        for uid in take:
            f = self.fetched[uid]
            entries.append(
                ArchiveEntry(
                    source_key=f.candidate.source_key,
                    item_id=f.candidate.id,
                    uid=uid,
                    ref=f.candidate.ref,
                    archived_at=loader.iso(now) or "",
                    request=request,
                    records=f.records,
                    superseded_by=(superseded or {}).get(uid),
                )
            )
        for e in entries:
            write_entry(self.slug, e)
        if entries:
            self.superseded.update(pipeline.load_entries(self.slug, self.cfg, entries).superseded)
        if entries and embeddings.is_warm():
            embeddings.embed_pending(self.slug, sources=take)
        self.loaded += take
        return take
