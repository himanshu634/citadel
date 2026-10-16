// purpose: Ask one role (pm or qa) about one gap. Idempotent: one consult per role per gap,
//          uid consult:<gap>:<role> (agents.keeper.model.consult_uid); a second post changes
//          nothing.
// params:  $gap (Gap.uid), $role ('pm' | 'qa'), $now (ISO)
// returns: uid, created (bool)
// example: store.write("ledger/post_consult", "citadel_keeper", {"gap": "gap:1a2b3c4d5e6f",
//          "role": "pm", "now": "2026-10-17T10:00:00Z"})
OPTIONAL MATCH (old:Consult {uid: 'consult:' + $gap + ':' + $role})
WITH old
MERGE (c:Consult {uid: 'consult:' + $gap + ':' + $role})
ON CREATE SET c.gap = $gap,
              c.role = $role,
              c.status = 'open',
              c.cites = [],
              c.created_at = $now
RETURN c.uid AS uid, old IS NULL AS created
