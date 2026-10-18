// purpose: Store comment text as Chunks FROM its work item, so the "why" behind a PR lives in
//          the graph (the embed stage fills the vector). The schema has no Comment node by design.
//          A long comment is cut into pieces (loader._pieces); `comment_uid` and `idx` say which
//          comment and which piece, so prune_comment_chunks can drop pieces a shorter text lost
//          and counts can take only piece 0 (`coalesce(c.idx, 0) = 0`: older chunks have no idx).
// params:  $company, $rows: [{uid, comment_uid, idx, work_item_uid, author_uid, text, text_hash,
//          created_at, ts, source, url}]
// returns: n (chunks written; rows whose work item is missing are dropped)
// example: loader.load(...) runs it after WorkItem nodes
UNWIND $rows AS row
MATCH (w:WorkItem {uid: row.work_item_uid})
MERGE (c:Chunk {uid: row.uid})
SET c:Node,
    c.company = $company,
    c.kind = 'comment',
    c.comment_uid = row.comment_uid,
    c.idx = row.idx,
    c.text = row.text,
    c.text_hash = row.text_hash,
    c.author_uid = row.author_uid,
    c.created_at = row.created_at,
    c.ts = row.ts,
    c.source = row.source,
    c.url = row.url
MERGE (c)-[:FROM]->(w)
RETURN count(c) AS n
