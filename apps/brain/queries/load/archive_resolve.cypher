// purpose: Turn unresolved refs into edges once their target is loaded: every WorkItem whose
//          unresolved_refs holds the `ref` of an archived WorkItem or Document gets MENTIONS to
//          it, and the ref is dropped from the list. Idempotent: a second run finds no refs.
// params:  none
// returns: n (edges made), one row per part: archived WorkItems, then archived Documents
// notes:   One part per kind label, so each starts from a label scan; a label-less
//          `MATCH (a) WHERE a:WorkItem OR a:Document` scans every node, chunks included, and
//          this runs after every ingest.
// example: loader.resolve_refs("falkordb")
MATCH (a:WorkItem)
WHERE a.ref IS NOT NULL
MATCH (w:WorkItem)
WHERE a.ref IN coalesce(w.unresolved_refs, [])
MERGE (w)-[:MENTIONS]->(a)
SET w.unresolved_refs = [r IN w.unresolved_refs WHERE r <> a.ref]
RETURN count(a) AS n
UNION ALL
MATCH (a:Document)
WHERE a.ref IS NOT NULL
MATCH (w:WorkItem)
WHERE a.ref IN coalesce(w.unresolved_refs, [])
MERGE (w)-[:MENTIONS]->(a)
SET w.unresolved_refs = [r IN w.unresolved_refs WHERE r <> a.ref]
RETURN count(a) AS n
