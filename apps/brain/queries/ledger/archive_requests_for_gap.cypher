// purpose: The requests raised for one gap, most recently updated first.
// params:  $gap (Gap.uid)
// returns: request (its properties; agents.keeper.model.ArchiveRequest)
// example: store.read("ledger/archive_requests_for_gap", {"gap": "gap:1a2b3c4d5e6f"})
MATCH (r:ArchiveRequest {gap: $gap})
RETURN properties(r) AS request
ORDER BY r.updated_at DESC, r.uid DESC
