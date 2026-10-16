"""The one priority formula every queue sorts by, so all agents agree on what is urgent.

Phase 2 ships the same formula as the `citadel.priority` UDF (queries/udfs/citadel.js); a test
pins both to the same numbers.
"""

from __future__ import annotations

import math

DAY = 86_400
SEVERITY = {"P0": 4.0, "P1": 3.0, "P2": 2.0, "P3": 1.0}


def decay(ts: int, now: int, half_life_days: float) -> float:
    """Recency weight: 1 now, halving every `half_life_days`."""
    return 0.5 ** (max(now - ts, 0) / (half_life_days * DAY))


def priority(pagerank: float, mentions: int, age_days: float, severity: float) -> float:
    """Higher is more urgent: severity, scaled up for central systems (PageRank over
    CO_CHANGES), often-referenced issues, and age (capped at 30 days, where it doubles)."""
    return severity * (1 + pagerank) * (1 + math.log1p(mentions)) * (1 + min(age_days, 30) / 30)


def task_score(
    priority_label: str | None, pagerank: float, mentions: int, created_ts: int, now: int
) -> float:
    severity = SEVERITY.get(priority_label or "", 1.5)  # untriaged: between P2 and P3
    return priority(pagerank, mentions, max(now - created_ts, 0) / DAY, severity)
