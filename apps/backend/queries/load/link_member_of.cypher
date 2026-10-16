// purpose: (Person)-[:MEMBER_OF]->(Team) from canonical Link records. One file per allowed (rel, from, to)
//          combination: relationship types and labels cannot be Cypher parameters, and fixed
//          labels let both MATCHes use the uid index. Rows whose ends are missing are dropped.
// params:  $rows: [{from_uid, to_uid, source}]
// returns: n (edges ensured)
// example: Link(rel="MEMBER_OF", from_label="Person", to_label="Team", from_uid=..., to_uid=...)
UNWIND $rows AS row
MATCH (a:Person {uid: row.from_uid})
MATCH (b:Team {uid: row.to_uid})
MERGE (a)-[r:MEMBER_OF]->(b)
SET r.source = row.source
RETURN count(r) AS n
