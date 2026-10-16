// purpose: Upsert changes (commits). kind is the conventional-commit type (feat/fix/...), parsed
//          by normalize. ts (epoch seconds) is what recency-weighted expertise uses.
// params:  $company, $rows: [{uid, sha, date, ts, kind, subject, source, url}]
// returns: n (rows written)
// example: loader.load("falkordb", [Change(uid="github:FalkorDB/FalkorDB:commit:abc123", ...)])
UNWIND $rows AS row
MERGE (c:Change {uid: row.uid})
SET c.company = $company,
    c.sha = row.sha,
    c.date = row.date,
    c.ts = row.ts,
    c.kind = row.kind,
    c.subject = row.subject,
    c.source = row.source,
    c.url = row.url
RETURN count(c) AS n
