// purpose: Upsert work items: PRs, issues, tickets and threads share one label, told apart by
//          `kind`. Timestamps are ISO strings for display plus *_ts epoch seconds for math
//          (FalkorDB has no epoch accessor on temporal values).
// params:  $company, $rows: [{uid, kind, number, title, body, state, created_at, created_ts,
//          updated_at, closed_at, closed_ts, merged_at, labels, container, source, url}]
// returns: n (rows written)
// example: loader.load("falkordb", [WorkItem(uid="github:FalkorDB/FalkorDB:pr:3330", ...)])
UNWIND $rows AS row
MERGE (w:WorkItem {uid: row.uid})
SET w.company = $company,
    w.kind = row.kind,
    w.number = row.number,
    w.title = row.title,
    w.body = row.body,
    w.state = row.state,
    w.created_at = row.created_at,
    w.created_ts = row.created_ts,
    w.updated_at = row.updated_at,
    w.closed_at = row.closed_at,
    w.closed_ts = row.closed_ts,
    w.merged_at = row.merged_at,
    w.labels = row.labels,
    w.container = row.container,
    w.source = row.source,
    w.url = row.url
RETURN count(w) AS n
