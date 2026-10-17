// purpose: A running review's sign of life at a job boundary, so a start or a restart does not
//          take it for one whose process is gone (review_start, review_stop_running).
// params:  $uid (Review uid), $now (ISO)
// returns: uid. No rows: no such review is running.
// example: store.write("ledger/review_heartbeat", "citadel_keeper", {"uid": "review:1a2b3c4d",
//          "now": "2026-10-17T10:02:00Z"})
MATCH (r:Review {uid: $uid})
WHERE r.state = 'running'
SET r.heartbeat_at = $now
RETURN r.uid AS uid
