// purpose: Record that one configured source was ingested: its cursor (latest record timestamp
//          seen) and when. The next ingest skips records older than the cursor unless --full.
// params:  $company, $uid, $adapter, $key, $cursor, $window_since, $last_run, $records
//          window_since is stored so a changed config window forces a full reload.
// returns: uid
// example: pipeline.ingest("falkordb") calls it once per source
MERGE (s:SyncState {uid: $uid})
SET s.company = $company,
    s.adapter = $adapter,
    s.key = $key,
    s.cursor = $cursor,
    s.window_since = $window_since,
    s.last_run = $last_run,
    s.records = $records
RETURN s.uid AS uid
