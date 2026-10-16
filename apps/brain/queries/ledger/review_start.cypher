// purpose: Start a review run, only when no review is running (one per company at a time).
//          `seq` numbers reviews in start order, so the latest is found even within one second.
// params:  $uid, $slug, $trigger ('build' | 'manual' | 'approval'), $budget, $now (ISO)
// returns: uid. No rows: a review is already running.
// notes:   The store fills $slug.
// example: store.write("ledger/review_start", "citadel_keeper", {"uid": "review:1a2b3c4d",
//          "trigger": "manual", "budget": 5, "now": "2026-10-17T10:00:00Z"})
OPTIONAL MATCH (r:Review)
WITH count(r) AS n, sum(CASE WHEN r.state = 'running' THEN 1 ELSE 0 END) AS running
WHERE running = 0
CREATE (v:Review {
    uid: $uid,
    seq: n,
    slug: $slug,
    trigger: $trigger,
    state: 'running',
    budget: $budget,
    started_at: $now
})
RETURN v.uid AS uid
