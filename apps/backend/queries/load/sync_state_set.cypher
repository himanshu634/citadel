// purpose: Record that one configured source was ingested: its cursor (latest record timestamp
//          seen) and when. The next ingest skips records older than the cursor unless --full.
// params:  $company, $uid, $adapter, $key, $cursor, $last_run, $records
// returns: uid
// example: pipeline.ingest("falkordb") calls it once per source
MERGE (s:SyncState {uid: $uid})
SET s.company = $company,
    s.adapter = $adapter,
    s.key = $key,
    s.cursor = $cursor,
    s.last_run = $last_run,
    s.records = $records
RETURN s.uid AS uid
