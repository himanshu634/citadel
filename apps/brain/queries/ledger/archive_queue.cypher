// purpose: The Archivist's queue: open requests, oldest first.
// params:  $limit
// returns: request (its properties; agents.keeper.model.ArchiveRequest)
// example: store.read("ledger/archive_queue", {"limit": 5})
MATCH (r:ArchiveRequest {status: 'open'})
RETURN properties(r) AS request
ORDER BY r.created_at, r.uid
LIMIT $limit
