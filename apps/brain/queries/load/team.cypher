// purpose: Upsert teams (from CODEOWNERS `@org/team`, or a JSONL export). MERGE on uid.
// params:  $company, $rows: [{uid, name, source, url}]
// returns: n (rows written)
// example: loader.load("synthetic", [Team(name="payments")])
UNWIND $rows AS row
MERGE (t:Team {uid: row.uid})
SET t:Node,
    t.company = $company,
    t.name = row.name,
    t.url = coalesce(row.url, t.url),
    t.source = CASE WHEN row.source = 'derived' AND t.source IS NOT NULL THEN t.source ELSE row.source END
RETURN count(t) AS n
