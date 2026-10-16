// purpose: Read the ingest cursor for one configured source (see sync_state_set).
// params:  $uid  e.g. "sync:github:FalkorDB/FalkorDB"
// returns: cursor (ISO timestamp or null), last_run
// example: pipeline.ingest("falkordb") reads it before loading
MATCH (s:SyncState {uid: $uid})
RETURN s.cursor AS cursor, s.last_run AS last_run
