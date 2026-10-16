// purpose: Upsert systems (code areas). Names come from the company's path rules, so the same
//          folder always maps to the same System node. path_rule records which rule produced it.
// params:  $company, $rows: [{uid, name, path_rule, source}]
// returns: n (rows written)
// example: loader.load("falkordb", [System(name="Indexing", path_rule="src/index/**")])
UNWIND $rows AS row
MERGE (s:System {uid: row.uid})
SET s.company = $company,
    s.name = row.name,
    s.path_rule = coalesce(row.path_rule, s.path_rule),
    s.source = CASE WHEN row.source = 'derived' AND s.source IS NOT NULL THEN s.source ELSE row.source END
RETURN count(s) AS n
