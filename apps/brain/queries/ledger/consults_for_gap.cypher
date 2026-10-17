// purpose: The consults of a gap's current attempt (consult.attempt = gap.attempts), answered or
//          not, by role: what the Keeper reads to decide. Consults of earlier attempts are history.
// params:  $gap (Gap.uid)
// returns: consult (its properties; agents.keeper.model.Consult). No rows for an unknown gap.
// example: store.read("ledger/consults_for_gap", {"gap": "gap:1a2b3c4d5e6f"})
MATCH (g:Gap {uid: $gap})
MATCH (c:Consult {gap: $gap})
WHERE c.attempt = g.attempts
RETURN properties(c) AS consult
ORDER BY c.role
