// purpose: A role's answer to its consult: a draft claim citing uids it saw, or can_ground false.
//          Guarded on status 'open', so a consult is answered once.
// params:  $consult (Consult.uid), $can_ground (bool), $kind, $subject, $statement, $value
//          (each may be null when it cannot ground), $cites: [uid], $now (ISO)
// returns: uid, status. No rows: the consult is not open (or does not exist).
// example: store.write("ledger/answer_consult", "citadel_pm", {"consult": "consult:gap:1:pm",
//          "can_ground": true, "kind": "owner", "subject": "system:billing",
//          "statement": "Alice owns Billing.", "value": "person:alice", "cites": ["pr:1"],
//          "now": "2026-10-17T10:02:00Z"})
MATCH (c:Consult {uid: $consult})
WHERE c.status = 'open'
SET c.status = 'answered',
    c.can_ground = $can_ground,
    c.kind = $kind,
    c.subject = $subject,
    c.statement = $statement,
    c.value = $value,
    c.cites = $cites,
    c.answered_at = $now
RETURN c.uid AS uid, c.status AS status
