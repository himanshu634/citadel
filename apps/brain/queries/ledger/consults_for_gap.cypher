// purpose: The consults of a gap's current round (consult.attempt = gap.attempts, and the round
//          after the gap asked the Archivist once it has), answered or not, by role: what the
//          Keeper reads to decide. Consults of earlier rounds are history.
// params:  $gap (Gap.uid)
// returns: consult (its properties; agents.keeper.model.Consult). No rows for an unknown gap.
// example: store.read("ledger/consults_for_gap", {"gap": "gap:1a2b3c4d5e6f"})
MATCH (g:Gap {uid: $gap})
MATCH (c:Consult {gap: $gap})
WHERE c.attempt = g.attempts
  AND coalesce(c.archive, false) = coalesce(g.archive_asked, false)
RETURN properties(c) AS consult
ORDER BY c.role
