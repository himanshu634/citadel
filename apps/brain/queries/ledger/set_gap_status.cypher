// purpose: Move a gap to another status, guarded: it matches only while the gap's status is one
//          of $from, so of two racing moves only one wins. Records the reason and may add one to
//          attempts (a rejected claim).
// params:  $uid, $from: [status], $to, $reason (or null), $now (ISO), $attempts_inc (0 or 1)
// returns: uid, status. No rows: the gap's status was not in $from (or there is no such gap).
// example: store.write("ledger/set_gap_status", "citadel_keeper", {"uid": "gap:1a2b3c4d5e6f",
//          "from": ["in_review"], "to": "open", "reason": "rejected", "now": "...",
//          "attempts_inc": 1})
MATCH (g:Gap {uid: $uid})
WHERE g.status IN $from
SET g.status = $to,
    g.reason = $reason,
    g.updated_at = $now,
    g.attempts = g.attempts + $attempts_inc
RETURN g.uid AS uid, g.status AS status
