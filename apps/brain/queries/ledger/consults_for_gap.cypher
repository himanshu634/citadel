// purpose: Every consult of one gap (answered or not), by role: what the Keeper reads to decide.
// params:  $gap (Gap.uid)
// returns: consult (its properties; agents.keeper.model.Consult)
// example: store.read("ledger/consults_for_gap", {"gap": "gap:1a2b3c4d5e6f"})
MATCH (c:Consult {gap: $gap})
RETURN properties(c) AS consult
ORDER BY c.role
