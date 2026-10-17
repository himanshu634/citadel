// purpose: What the sources say about a claim's subject: whether it exists, what it is, and who
//          is declared to own it (OWNS, from CODEOWNERS). A Keeper claim that disagrees with these
//          is not accepted ("sources win").
// params:  $uid (the subject's uid)
// returns: label, name (a System's name, else null), declared_owners ([uid] of the people and
//          teams that OWN it, sorted). No row: the subject is not in the brain.
// example: keeper.source_facts("synthetic", "system:Auth")
MATCH (n {uid: $uid})
OPTIONAL MATCH (o)-[:OWNS]->(n)
WITH n, o ORDER BY o.uid
RETURN labels(n)[0] AS label, n.name AS name,
       [x IN collect(o.uid) WHERE x IS NOT NULL] AS declared_owners
