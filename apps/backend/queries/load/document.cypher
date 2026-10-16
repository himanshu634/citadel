// purpose: Upsert documents (READMEs, design docs, ADRs, published notes).
// params:  $company, $rows: [{uid, path, title, body, updated_at, source, url}]
// returns: n (rows written)
// example: loader.load("falkordb", [Document(uid="github:FalkorDB/FalkorDB:doc:README.md", ...)])
UNWIND $rows AS row
MERGE (d:Document {uid: row.uid})
SET d.company = $company,
    d.path = row.path,
    d.title = row.title,
    d.body = row.body,
    d.updated_at = row.updated_at,
    d.source = row.source,
    d.url = row.url
RETURN count(d) AS n
