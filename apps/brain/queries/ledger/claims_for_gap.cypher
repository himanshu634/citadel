// purpose: The claims written for one gap in the given statuses, most recently updated first:
//          the decide queue skips a gap whose claim waits for a lead (pending_approval).
// params:  $gap (Gap.uid), $statuses: [status]
// returns: claim (its properties; agents.keeper.model.Claim)
// example: store.read("ledger/claims_for_gap", {"gap": "gap:1a2b3c4d5e6f",
//          "statuses": ["pending_approval"]})
MATCH (c:Claim {gap: $gap})
WHERE c.status IN $statuses
RETURN properties(c) AS claim
ORDER BY c.updated_at DESC, c.uid DESC
