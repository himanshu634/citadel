// purpose: (WorkItem)-[:MENTIONS]->(WorkItem) from canonical Link records. One file per allowed (rel, from, to)
//          combination: relationship types and labels cannot be Cypher parameters, and fixed
//          labels let both MATCHes use the uid index. Rows whose ends are missing are dropped.
// params:  $rows: [{from_uid, to_uid, source}]
// returns: n (edges ensured)
// example: Link(rel="MENTIONS", from_label="WorkItem", to_label="WorkItem", from_uid=..., to_uid=...)
UNWIND $rows AS row
MATCH (a:WorkItem {uid: row.from_uid})
MATCH (b:WorkItem {uid: row.to_uid})
MERGE (a)-[r:MENTIONS]->(b)
SET r.source = row.source
RETURN count(r) AS n
