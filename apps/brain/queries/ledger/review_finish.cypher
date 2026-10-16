// purpose: End a running review: done, stopped, failed or skipped, with why it stopped early.
// params:  $uid, $state, $stop (or null), $now (ISO)
// returns: uid, state. No rows: no such review is running.
// example: store.write("ledger/review_finish", "citadel_keeper", {"uid": "review:1a2b3c4d",
//          "state": "done", "stop": null, "now": "2026-10-17T10:04:00Z"})
MATCH (r:Review {uid: $uid})
WHERE r.state = 'running'
SET r.state = $state,
    r.stop = $stop,
    r.ended_at = $now
RETURN r.uid AS uid, r.state AS state
