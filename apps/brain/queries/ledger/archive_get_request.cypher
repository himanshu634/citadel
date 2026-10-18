// purpose: One Archivist request by uid.
// params:  $uid
// returns: request (its properties; agents.keeper.model.ArchiveRequest)
// example: store.read("ledger/archive_get_request", {"uid": "archive:1a2b3c4d5e6f"})
MATCH (r:ArchiveRequest {uid: $uid})
RETURN properties(r) AS request
