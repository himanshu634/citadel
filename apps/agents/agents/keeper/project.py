"""Re-projection: after a build, check every accepted claim against the new sources and write it
back into brain_<slug>.

Why: a rebuild deletes brain_<slug>, and with it the projected `Claim` nodes, while the ledger
(keeper_<slug>) keeps them. And the new sources may now say something else ("Sources win",
docs/superpowers/specs/2026-10-16-keeper-design.md). So for every accepted claim, in this order:

1. The sources contradict it: `superseded` (valid_to set, retired in the brain), logged
   `claim_superseded` with why "source: <what the sources say>". Its gap stays resolved.
2. Otherwise it is projected (MERGE on uid, so this is idempotent). A claim whose subject or
   every evidence uid is gone is `stale` instead: retired in the brain, logged `claim_stale`,
   and its gap reopens (no attempt used up).

A missing brain_<slug> raises `BrainUnavailable` before anything is written: projection would
report every claim missing, and every one would wrongly go stale.

    reproject(store, "synthetic", brain=decide.DEFAULT_BRAIN, now="2026-10-17T10:00:00Z")
    # -> {"projected": 4, "stale": 0, "superseded_by_source": 1}
"""

from __future__ import annotations

from agents.keeper.decide import (
    EARLIER_LIMIT,
    BrainFacts,
    _gap,
    _log,
    _reopen,
    _set_claim,
    brain_present,
)
from agents.keeper.model import Claim
from agents.keeper.rules import conflict
from agents.work.store import WorkStore

STALE_WHY = "projection: its subject or every evidence uid is gone from the brain"


def reproject(store: WorkStore, slug: str, *, brain: BrainFacts, now: str) -> dict[str, int]:
    """Re-check and re-project every accepted claim. Returns the counts of each outcome."""
    brain_present(brain, slug)
    accepted = [
        Claim(**c)
        for c in store.read("ledger/claims", {"statuses": ["accepted"], "limit": EARLIER_LIMIT})
    ]
    out = {"projected": 0, "stale": 0, "superseded_by_source": 0}

    keep: list[Claim] = []
    for claim in accepted:
        clash = conflict(claim.kind, claim.value, brain.source_facts(slug, claim.subject))
        if not clash:
            keep.append(claim)
            continue
        why = f"source: {clash}"
        if _set_claim(store, now, claim.uid, "superseded", frm=["accepted"], why=why,
                      valid_to=now):  # fmt: skip
            _log(store, now, "keeper", "claim_superseded", gap=claim.gap, claim=claim.uid,
                 why=why, evidence=[claim.subject])  # fmt: skip
            brain.retire(slug, claim.uid, "superseded", now)  # after the log, as decide does
            out["superseded_by_source"] += 1

    if not keep:
        return out
    missing = set(brain.project(slug, [c.model_dump() for c in keep]))
    if missing:
        brain_present(brain, slug)  # not every claim missing because the whole graph is
    out["projected"] = len(keep) - len(missing)
    for claim in keep:
        if claim.uid not in missing:
            continue
        if not _set_claim(store, now, claim.uid, "stale", frm=["accepted"], why=STALE_WHY):
            continue
        gap = _gap(store, claim.gap) if claim.gap else None
        if gap is not None:
            _reopen(store, now, gap, STALE_WHY, rejected=False, frm=["in_review", "resolved"])
        _log(store, now, "keeper", "claim_stale", gap=claim.gap, claim=claim.uid, why=STALE_WHY,
             evidence=claim.evidence)  # fmt: skip
        brain.retire(slug, claim.uid, "stale", now)
        out["stale"] += 1
    return out
