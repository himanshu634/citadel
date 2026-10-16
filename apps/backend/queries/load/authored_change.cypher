// purpose: Link a Change to its author: (Person)-[:AUTHORED]->(Change). Both nodes must already
//          exist (people and Changes are loaded first); MATCH drops rows whose end is missing.
//          One file per target label, because labels cannot be Cypher parameters.
// params:  $rows: [{person_uid, target_uid}]
// returns: n (edges ensured)
// example: loader.load(...) runs it after the Change nodes
UNWIND $rows AS row
MATCH (p:Person {uid: row.person_uid})
MATCH (x:Change {uid: row.target_uid})
MERGE (p)-[r:AUTHORED]->(x)
RETURN count(r) AS n
