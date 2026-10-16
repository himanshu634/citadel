// purpose: The newest PRs, issues, tickets and threads, so an overview can show "what happened
//          lately". Newest first by the latest of created and closed; `last_at` is that
//          moment as the ISO string the adapter stored (a merged PR's closed_at is its merge time;
//          merged_at is not read).
// params:  $limit (int)
// returns: uid, kind, number, title, state, url, author, last_at, systems (sorted names of systems
//          the item changed through its commits or mentions)
// example: make query TOOL=recent_work_items P="limit=5"
MATCH (w:WorkItem)
WITH w, CASE WHEN w.closed_ts IS NOT NULL AND w.closed_ts >= coalesce(w.created_ts, 0)
             THEN w.closed_ts ELSE w.created_ts END AS at_ts,
          CASE WHEN w.closed_ts IS NOT NULL AND w.closed_ts >= coalesce(w.created_ts, 0)
             THEN w.closed_at ELSE w.created_at END AS last_at
ORDER BY at_ts DESC, w.uid
LIMIT $limit
OPTIONAL MATCH (a:Person)-[:AUTHORED]->(w)
WITH w, at_ts, last_at, head(collect(a.login)) AS author
OPTIONAL MATCH (w)<-[:PART_OF]-(:Change)-[:TOUCHES]->(cs:System)
WITH w, at_ts, last_at, author, collect(DISTINCT cs.name) AS changed
OPTIONAL MATCH (w)-[:MENTIONS]->(ms:System)
WITH w, at_ts, last_at, author, changed, collect(DISTINCT ms.name) AS mentioned
WITH w, at_ts, last_at, author,
     list.sort(changed + [x IN mentioned WHERE NOT x IN changed]) AS systems
RETURN w.uid AS uid, w.kind AS kind, w.number AS number, w.title AS title, w.state AS state,
       w.url AS url, author, last_at, systems
ORDER BY at_ts DESC, uid
