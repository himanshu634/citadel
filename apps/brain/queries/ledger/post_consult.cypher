// purpose: Ask one role (pm or qa) about one attempt at a gap. Idempotent per (gap, role,
//          attempt): uid consult:<gap>:<role>:<attempt> (agents.keeper.model.consult_uid); a
//          second post changes nothing. A gap reopened after a rejected claim has attempts + 1,
//          so it is asked again.
// params:  $gap (Gap.uid), $role ('pm' | 'qa'), $attempt (the gap's attempts now), $now (ISO)
// returns: uid, created (bool)
// example: store.write("ledger/post_consult", "citadel_keeper", {"gap": "gap:1a2b3c4d5e6f",
//          "role": "pm", "attempt": 0, "now": "2026-10-17T10:00:00Z"})
OPTIONAL MATCH (old:Consult {uid: 'consult:' + $gap + ':' + $role + ':' + toString($attempt)})
WITH old
MERGE (c:Consult {uid: 'consult:' + $gap + ':' + $role + ':' + toString($attempt)})
ON CREATE SET c.gap = $gap,
              c.role = $role,
              c.attempt = $attempt,
              c.status = 'open',
              c.cites = [],
              c.created_at = $now
RETURN c.uid AS uid, old IS NULL AS created
