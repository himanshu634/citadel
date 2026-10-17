// purpose: Claims in the given statuses, most recently updated first (the approvals list, the
//          accepted claims to re-project after a build).
// params:  $statuses: [status], $limit
// returns: claim (its properties; agents.keeper.model.Claim)
// example: store.read("ledger/claims", {"statuses": ["pending_approval"], "limit": 50})
MATCH (c:Claim)
WHERE c.status IN $statuses
RETURN properties(c) AS claim
ORDER BY c.updated_at DESC, c.uid DESC
LIMIT $limit
