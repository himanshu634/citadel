// purpose: Move a claim to another status, guarded: it matches only while the claim's status is
//          one of $from, so of two racing approvals (or approve and reject) only one wins.
//          - accepted: valid_from is set (if not yet), approved_by = $by;
//          - rejected: approved_by = $by (who decided);
//          - pending_approval (an accept undone): approved_by and valid_from are cleared;
//          - $why, when given, replaces why (why the claim has its status now);
//          - $valid_to, when given, is set (superseded);
//          - $conflict, when given, is set (conflicts_with_source: what the sources say).
// params:  $uid, $from: [status], $to, $by (or null), $why (or null), $now (ISO),
//          $valid_to (or null), $conflict (or null)
// returns: uid, status. No rows: the claim's status was not in $from (or there is no claim).
// example: store.write("ledger/set_claim_status", "citadel_keeper", {"uid": "claim:1a2b3c4d5e6f",
//          "from": ["pending_approval"], "to": "accepted", "by": "Dana", "why": "Checked.",
//          "now": "2026-10-17T11:00:00Z"})
MATCH (c:Claim {uid: $uid})
WHERE c.status IN $from
SET c.status = $to,
    c.updated_at = $now,
    c.valid_from = CASE WHEN $to = 'accepted' THEN coalesce(c.valid_from, $now)
                        WHEN $to = 'pending_approval' THEN null
                        ELSE c.valid_from END,
    c.approved_by = CASE WHEN $to = 'pending_approval' THEN null
                         WHEN $to IN ['accepted', 'rejected'] AND $by IS NOT NULL THEN $by
                         ELSE c.approved_by END,
    c.why = coalesce($why, c.why),
    c.valid_to = coalesce($valid_to, c.valid_to),
    c.conflict = coalesce($conflict, c.conflict)
RETURN c.uid AS uid, c.status AS status
