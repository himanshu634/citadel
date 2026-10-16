// purpose: Store comment text as a Chunk FROM its work item, so the "why" behind a PR lives in
//          the graph (embedding is filled later). The schema has no Comment node by design.
// params:  $company, $rows: [{uid, work_item_uid, author_uid, text, text_hash, created_at, ts,
//          source, url}]
// returns: n (chunks written; rows whose work item is missing are dropped)
// example: loader.load(...) runs it after WorkItem nodes
UNWIND $rows AS row
MATCH (w:WorkItem {uid: row.work_item_uid})
MERGE (c:Chunk {uid: row.uid})
SET c.company = $company,
    c.kind = 'comment',
    c.text = row.text,
    c.text_hash = row.text_hash,
    c.author_uid = row.author_uid,
    c.created_at = row.created_at,
    c.ts = row.ts,
    c.source = row.source,
    c.url = row.url
MERGE (c)-[:FROM]->(w)
RETURN count(c) AS n
