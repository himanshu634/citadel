// purpose: (WorkItem)-[:BLOCKS]->(WorkItem) from canonical Link records. `origin` (the adapter
//          key) and `uid` (the Link's uid) are stored on the edge so prune_blocks can delete the
//          edges of one source that a later load no longer has. Rows whose ends are missing are
//          dropped.
// params:  $rows: [{from_uid, to_uid, source, origin, uid}]
// returns: n (edges ensured)
// example: Link(rel="BLOCKS", from_label="WorkItem", to_label="WorkItem", from_uid=..., to_uid=...)
UNWIND $rows AS row
MATCH (a:WorkItem {uid: row.from_uid})
MATCH (b:WorkItem {uid: row.to_uid})
MERGE (a)-[r:BLOCKS]->(b)
SET r.source = row.source,
    r.origin = row.origin,
    r.uid = row.uid
RETURN count(r) AS n
