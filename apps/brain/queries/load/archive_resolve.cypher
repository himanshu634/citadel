// purpose: Turn unresolved refs into edges once their target is loaded: every WorkItem whose
//          unresolved_refs holds the `ref` of an archived WorkItem or Document gets MENTIONS to
//          it, and the ref is dropped from the list. Idempotent: a second run finds no refs.
// params:  none
// returns: n (edges made)
// example: loader.resolve_refs("falkordb")
MATCH (a)
WHERE (a:WorkItem OR a:Document) AND a.ref IS NOT NULL
MATCH (w:WorkItem)
WHERE a.ref IN coalesce(w.unresolved_refs, [])
MERGE (w)-[:MENTIONS]->(a)
SET w.unresolved_refs = [r IN w.unresolved_refs WHERE r <> a.ref]
RETURN count(a) AS n
