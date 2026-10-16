// purpose: Store a PR/issue/ticket body (title first) as a Chunk FROM its work item, so semantic
//          search finds work by what it says. `text_hash` lets the embed stage re-embed only the
//          chunks whose text changed.
// params:  $company, $rows: [{uid, work_item_uid, text, text_hash, created_at, ts, source, url}]
// returns: n (chunks written; rows whose work item is missing are dropped)
// example: loader.load(...) runs it after WorkItem nodes
UNWIND $rows AS row
MATCH (w:WorkItem {uid: row.work_item_uid})
MERGE (c:Chunk {uid: row.uid})
SET c.company = $company,
    c.kind = 'work_item',
    c.text = row.text,
    c.text_hash = row.text_hash,
    c.created_at = row.created_at,
    c.ts = row.ts,
    c.source = row.source,
    c.url = row.url
MERGE (c)-[:FROM]->(w)
RETURN count(c) AS n
