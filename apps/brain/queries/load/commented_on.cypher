// purpose: (Person)-[:COMMENTED_ON {count, last_at}]->(WorkItem). The count is recomputed from
//          the comment Chunks already in the graph, so it stays right on incremental ingests. A
//          long comment cut into pieces counts once: only piece 0 (older chunks have no idx).
// params:  $rows: [{person_uid, work_item_uid}]  (distinct pairs)
// returns: n (edges ensured)
// example: loader.load(...) runs it after comment_chunk
UNWIND $rows AS row
MATCH (p:Person {uid: row.person_uid})
MATCH (w:WorkItem {uid: row.work_item_uid})
MERGE (p)-[r:COMMENTED_ON]->(w)
WITH p, w, r
MATCH (c:Chunk {kind: 'comment'})-[:FROM]->(w)
WHERE c.author_uid = p.uid AND coalesce(c.idx, 0) = 0
WITH r, count(c) AS cnt, max(c.ts) AS last_ts, max(c.created_at) AS last_at
SET r.count = cnt, r.last_ts = last_ts, r.last_at = last_at
RETURN count(r) AS n
