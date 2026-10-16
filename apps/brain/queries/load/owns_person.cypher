// purpose: Declared ownership: (Person)-[:OWNS {pattern}]->(System), e.g. from CODEOWNERS.
//          pattern holds the source pattern(s) that map to this system, comma separated.
//          Compare with derived expertise to find stale ownership.
// params:  $rows: [{owner_uid, system_uid, pattern, source}]
// returns: n (edges ensured)
// example: loader.load(...) runs it after Person and System nodes
UNWIND $rows AS row
MATCH (o:Person {uid: row.owner_uid})
MATCH (s:System {uid: row.system_uid})
MERGE (o)-[r:OWNS]->(s)
SET r.pattern = row.pattern, r.source = row.source
RETURN count(r) AS n
