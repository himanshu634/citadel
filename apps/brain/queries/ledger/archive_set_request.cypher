// purpose: Move a request to another status, guarded: it matches only while the request's status
//          is one of $from, so of two racing moves only one wins. Records the outcome, summary,
//          reason, partial flag and the calls used (the nullable ones clear when null).
// params:  $uid, $from: [status], $to, $outcome (found | nothing_found | already_in_brain, or
//          null), $summary, $reason, $partial (bool), $calls, $now (ISO)
// returns: uid, status. No rows: the status was not in $from (or there is no such request).
// example: store.write("ledger/archive_set_request", "citadel_archivist", {"uid": "archive:1a2b3c4d5e6f",
//          "from": ["running"], "to": "answered", "outcome": "found", "summary": "1 item",
//          "partial": false, "calls": 3, "now": "2026-10-17T10:01:00Z"})
MATCH (r:ArchiveRequest {uid: $uid})
WHERE r.status IN $from
SET r.status = $to,
    r.outcome = $outcome,
    r.summary = $summary,
    r.reason = $reason,
    r.partial = $partial,
    r.calls = $calls,
    r.updated_at = $now
RETURN r.uid AS uid, r.status AS status
