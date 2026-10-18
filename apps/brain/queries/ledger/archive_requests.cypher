// purpose: Requests in the given statuses, most recently updated first.
// params:  $statuses: [status], $limit
// returns: request (its properties; agents.keeper.model.ArchiveRequest)
// example: store.read("ledger/archive_requests", {"statuses": ["running"], "limit": 10})
MATCH (r:ArchiveRequest)
WHERE r.status IN $statuses
RETURN properties(r) AS request
ORDER BY r.updated_at DESC, r.uid DESC
LIMIT $limit
