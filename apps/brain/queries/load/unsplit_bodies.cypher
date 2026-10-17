// purpose: The work items whose text loader.backfill_chunks must (re)write: those with no body
//          chunk (a graph built before work items had them), and those whose body chunk was
//          written whole, before long text was cut (it has no idx). An incremental ingest never
//          reloads old items, so they would stay as they are.
// params:  none
// returns: uid, title, body, created_at, ts, source, url (what loader._write_body_chunks takes)
// example: loader.backfill_chunks("falkordb")
MATCH (w:WorkItem)
OPTIONAL MATCH (c:Chunk {uid: 'chunk:' + w.uid + ':body'})
WITH w, c
WHERE c IS NULL OR c.idx IS NULL
RETURN w.uid AS uid, w.title AS title, w.body AS body, w.created_at AS created_at,
       w.created_ts AS ts, w.source AS source, w.url AS url
ORDER BY uid
