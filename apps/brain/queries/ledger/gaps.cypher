// purpose: Gaps in the given statuses, most recently updated first.
// params:  $statuses: [status], $limit
// returns: gap (its properties; agents.keeper.model.Gap)
// example: store.read("ledger/gaps", {"statuses": ["open"], "limit": 10})
MATCH (g:Gap)
WHERE g.status IN $statuses
RETURN properties(g) AS gap
ORDER BY g.updated_at DESC, g.uid DESC
LIMIT $limit
