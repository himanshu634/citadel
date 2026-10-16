// purpose: What does a person have to do? Their open tickets (not done or canceled), most urgent
//          first: priority, then the nearest due date (no date last), then key. Each ticket lists
//          the open tickets that block it (blocked_by) and the open items it blocks (blocks),
//          with their assignees.
// params:  $person_uid ("person:<login>"), $limit (int, tickets)
// returns: person_uid, uid, key, title, url, state, status_category, priority, due_date,
//          container, blocked_by ([{uid, key, title, url, status_category, assignees}]),
//          blocks (same shape)
// example: make query TOOL=open_work_for P="login=carol"
MATCH (p:Person {uid: $person_uid})-[:ASSIGNED_TO]->(t:WorkItem {kind: 'ticket'})
WHERE t.status_category IS NOT NULL AND NOT t.status_category IN ['done', 'canceled']
WITH p, t
ORDER BY coalesce(t.priority_rank, 5), coalesce(t.due_ts, 9999999999), t.key
LIMIT $limit
OPTIONAL MATCH (b:WorkItem)-[:BLOCKS]->(t)
WHERE b.status_category IS NOT NULL AND NOT b.status_category IN ['done', 'canceled']
WITH p, t, collect(CASE WHEN b IS NULL THEN NULL ELSE {
       uid: b.uid, key: b.key, title: b.title, url: b.url, status_category: b.status_category,
       assignees: [(b)<-[:ASSIGNED_TO]-(bp:Person) | bp.login]} END) AS blocked_by
OPTIONAL MATCH (t)-[:BLOCKS]->(w:WorkItem)
WHERE w.status_category IS NOT NULL AND NOT w.status_category IN ['done', 'canceled']
WITH p, t, blocked_by, collect(CASE WHEN w IS NULL THEN NULL ELSE {
       uid: w.uid, key: w.key, title: w.title, url: w.url, status_category: w.status_category,
       assignees: [(w)<-[:ASSIGNED_TO]-(wp:Person) | wp.login]} END) AS blocks
RETURN p.uid AS person_uid, t.uid AS uid, t.key AS key, t.title AS title, t.url AS url,
       t.state AS state, t.status_category AS status_category, t.priority AS priority,
       t.due_date AS due_date, t.container AS container, blocked_by, blocks
ORDER BY coalesce(t.priority_rank, 5), coalesce(t.due_ts, 9999999999), t.key
