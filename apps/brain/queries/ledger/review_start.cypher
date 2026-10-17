// purpose: Start a review run, only when no live review is running (one per company at a time).
//          A running review whose heartbeat (else its start) is older than $stale_before has
//          lost its process: it is stopped (stop 'stale', ended $now) and the new one starts.
//          `seq` numbers reviews in start order, so the latest is found even within one second.
// params:  $uid, $slug, $trigger ('build' | 'manual' | 'approval'), $budget, $now (ISO),
//          $stale_before (ISO)
// returns: uid. No rows: a live review is already running.
// notes:   The store fills $slug, and $stale_before from $now (model.REVIEW_STALE_SECONDS).
//          Timestamps compare as text: every one is written as YYYY-MM-DDTHH:MM:SSZ (`iso`).
// example: store.write("ledger/review_start", "citadel_keeper", {"uid": "review:1a2b3c4d",
//          "trigger": "manual", "budget": 5, "now": "2026-10-17T10:00:00Z"})
OPTIONAL MATCH (a:Review)
WITH count(a) AS n
OPTIONAL MATCH (r:Review {state: 'running'})
WITH n, collect(r) AS running
WHERE all(x IN running WHERE coalesce(x.heartbeat_at, x.started_at) < $stale_before)
FOREACH (x IN running |
    SET x.state = 'stopped',
        x.stop = 'stale',
        x.ended_at = $now
)
CREATE (v:Review {
    uid: $uid,
    seq: n,
    slug: $slug,
    trigger: $trigger,
    state: 'running',
    budget: $budget,
    started_at: $now,
    heartbeat_at: $now
})
RETURN v.uid AS uid
