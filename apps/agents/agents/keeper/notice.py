"""Noticing: gaps the brain shows on its own, opened on the ledger after a build or a review.

Why: not every gap is a question someone asked. The brain can show that a system's declared
owner does little of its work (`stale_owner`) or that a busy system has no owner at all
(`unowned_hot_system`). Each such subject becomes a gap the review can pick, unless it is already
settled (docs/superpowers/specs/2026-10-16-keeper-design.md, "Gap lifecycle"):

- it has an accepted `owner` claim, or
- an `owner` claim about it has an open follow-up (pm is getting its source fixed), or
- its latest gap of the same kind was settled (`resolved`, `dismissed` or `needs_person`), so a
  settled subject does not reopen on every build.

The ledger dedupes noticing gaps on (kind, subject), so a subject already open or in review is
bumped, not opened again; only new gaps count toward `cap`, so a fresh brain cannot flood the
queue.

    notice(store, "synthetic", cap=10, now="2026-10-17T10:00:00Z")  # -> new gap uids
"""

from __future__ import annotations

from typing import Any, Protocol

from brain import keeper as brain_keeper

from agents.keeper.decide import DB_USER, _log
from agents.keeper.model import NOTICING_KINDS, gap_uid
from agents.work.store import WorkStore

SETTLED_BY = "owner"  # the claim kind that settles both noticing kinds
SETTLED_GAP = ("resolved", "dismissed", "needs_person")  # a latest gap here settles its subject
FOLLOWUP_LIMIT = 10_000  # open follow-ups read per pass


class Noticer(Protocol):
    def notice(self, slug: str, kind: str, limit: int) -> list[dict[str, Any]]: ...


def notice(
    store: WorkStore,
    slug: str,
    *,
    cap: int,
    brain: Noticer = brain_keeper,  # type: ignore[assignment]  # the module has `notice`
    now: str,
) -> list[str]:
    """Open a gap for each unsettled subject the noticing queries return, at most `cap` new ones
    in all; log `gap_opened` for each. Returns the new gap uids, in query order."""
    fixing = {
        f["claim"]
        for f in store.read("ledger/followups", {"status": "open", "limit": FOLLOWUP_LIMIT})
    }
    new: list[str] = []
    for kind in NOTICING_KINDS:
        for row in brain.notice(slug, kind, cap):
            if len(new) >= cap:
                return new
            if _settled(store, kind, row["subject"], fixing):
                continue
            params = {
                "uid": gap_uid(),
                "kind": kind,
                "text": row["text"],
                "subject": row["subject"],
                "about": list(row.get("about") or []),
                "now": now,
            }
            [opened] = store.write("ledger/open_gap", DB_USER, params)
            if opened["created"]:
                new.append(opened["uid"])
                _log(store, now, "keeper", "gap_opened", gap=opened["uid"], why=row["text"],
                     evidence=params["about"])  # fmt: skip
    return new


def _settled(store: WorkStore, kind: str, subject: str, fixing: set[str]) -> bool:
    """The subject's latest gap of this kind was settled; or it has an accepted owner claim, or
    an owner claim whose source is being fixed."""
    latest = store.read("ledger/latest_gap_for_subject", {"kind": kind, "subject": subject})
    if latest and latest[0]["status"] in SETTLED_GAP:
        return True
    claims = store.read(
        "ledger/claims_for_subject",
        {"kind": SETTLED_BY, "subject": subject, "statuses": ["accepted", "conflicts_with_source"]},
    )
    return any(c["status"] == "accepted" or c["uid"] in fixing for c in claims)
