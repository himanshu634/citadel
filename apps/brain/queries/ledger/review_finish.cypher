// purpose: End a running review: done, stopped, failed or skipped, with why it stopped early and
//          the gaps its Archivist runs sent back to open (the backend's follow-on review).
// params:  $uid, $state, $stop (or null), $archive_reopened: [gap uid] (the store fills []),
//          $now (ISO)
// returns: uid, state. No rows: no such review is running.
// example: store.write("ledger/review_finish", "citadel_keeper", {"uid": "review:1a2b3c4d",
//          "state": "done", "stop": null, "archive_reopened": [], "now": "2026-10-17T10:04:00Z"})
MATCH (r:Review {uid: $uid})
WHERE r.state = 'running'
SET r.state = $state,
    r.stop = $stop,
    r.archive_reopened = $archive_reopened,
    r.ended_at = $now
RETURN r.uid AS uid, r.state AS state
