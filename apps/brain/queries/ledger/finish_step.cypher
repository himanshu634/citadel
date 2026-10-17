// purpose: End a running step of a review: done or failed, with the rows it returned, its error
//          and the brain uids it touched. Ending a step of a running review is its heartbeat.
// params:  $review (Review uid), $n, $status ('done' | 'failed'), $count, $error (each may be
//          null), $touched: [brain uid], $at (ISO)
// returns: review, n, status. No rows: no such step is running.
// example: store.write("ledger/finish_step", "citadel_keeper", {"review": "review:1a2b3c4d",
//          "n": 1, "status": "done", "count": 2, "touched": ["system:Auth"],
//          "at": "2026-10-17T10:00:01Z"})
MATCH (s:ReviewStep {review: $review, n: $n})
WHERE s.status = 'running'
OPTIONAL MATCH (r:Review {uid: $review, state: 'running'})
SET s.status = $status,
    s.count = $count,
    s.error = $error,
    s.touched = $touched,
    s.ended_at = $at
FOREACH (x IN CASE WHEN r IS NULL THEN [] ELSE [r] END | SET x.heartbeat_at = $at)
RETURN s.review AS review, s.n AS n, s.status AS status
