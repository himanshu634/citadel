// purpose: Record that one archived item is replaced by a newer one: a SUPERSEDED_BY edge and a
//          `superseded_by` property (the newer uid) on the older node. Both ends match by uid
//          (the Node.uid index) among WorkItem and Document; nothing is written when either is
//          missing.
// params:  $uid (older node), $by_uid (newer node)
// returns: n (nodes marked: 1, or 0 when an end is missing)
// example: loader.mark_superseded("falkordb", "github:a/b:pr:9", "github:a/b:pr:40")
MATCH (a:Node {uid: $uid})
WHERE a:WorkItem OR a:Document
MATCH (b:Node {uid: $by_uid})
WHERE b:WorkItem OR b:Document
MERGE (a)-[:SUPERSEDED_BY]->(b)
SET a.superseded_by = b.uid
RETURN count(a) AS n
