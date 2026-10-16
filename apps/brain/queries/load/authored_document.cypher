// purpose: Link a Document to its author: (Person)-[:AUTHORED]->(Document). Both nodes must already
//          exist (people and Documents are loaded first); MATCH drops rows whose end is missing.
//          One file per target label, because labels cannot be Cypher parameters.
// params:  $rows: [{person_uid, target_uid}]
// returns: n (edges ensured)
// example: loader.load(...) runs it after the Document nodes
UNWIND $rows AS row
MATCH (p:Person {uid: row.person_uid})
MATCH (x:Document {uid: row.target_uid})
MERGE (p)-[r:AUTHORED]->(x)
RETURN count(r) AS n
