// purpose: The finds of the given requests, by request then item uid.
// params:  $requests: [ArchiveRequest.uid]
// returns: find (its properties; agents.keeper.model.ArchiveFind)
// example: store.read("ledger/archive_finds", {"requests": ["archive:1a2b3c4d5e6f"]})
MATCH (f:ArchiveFind)
WHERE f.request IN $requests
RETURN properties(f) AS find
ORDER BY f.request, f.uid
