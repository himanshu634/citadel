// purpose: Follow-up tasks, newest first, optionally in one status.
// params:  $status ('open' | 'done', or null: any), $limit
// returns: followup (its properties; agents.keeper.model.FollowUp)
// example: store.read("ledger/followups", {"status": "open", "limit": 20})
MATCH (f:FollowUp)
WHERE $status IS NULL OR f.status = $status
RETURN properties(f) AS followup
ORDER BY f.created_at DESC, f.uid DESC
LIMIT $limit
