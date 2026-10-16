// purpose: The recent story of a system: PRs whose commits touched it and PRs/issues that
//          mention it, newest first, with authors, reviewers and the issues each PR closes.
//          `via` says how the item is connected ('changed' = its commits touched the system,
//          'mentioned' = its text names a path in the system).
// params:  $system (System name), $limit (int)
// returns: uid, kind, number, title, state, url, created_at, closed_at, via, author,
//          reviewers ([{login, state}]), closes ([{number, uid, url}]), system_uid
// example: make query TOOL=work_history P="system=Auth limit=5"
MATCH (s:System {name: $system})
OPTIONAL MATCH (s)<-[:TOUCHES]-(:Change)-[:PART_OF]->(changed:WorkItem)
WITH s, collect(DISTINCT changed) AS changed_items
OPTIONAL MATCH (mentioning:WorkItem)-[:MENTIONS]->(s)
WITH s, changed_items, collect(DISTINCT mentioning) AS mentioned_items
UNWIND changed_items + [x IN mentioned_items WHERE NOT x IN changed_items] AS w
WITH s, w, CASE WHEN w IN changed_items THEN 'changed' ELSE 'mentioned' END AS via
ORDER BY coalesce(w.closed_ts, w.created_ts) DESC
LIMIT $limit
OPTIONAL MATCH (a:Person)-[:AUTHORED]->(w)
WITH s, w, via, a.login AS author
OPTIONAL MATCH (r:Person)-[rv:REVIEWED]->(w)
WITH s, w, via, author, collect({login: r.login, state: rv.state}) AS reviewed
OPTIONAL MATCH (w)-[:CLOSES]->(i:WorkItem)
WITH s, w, via, author, reviewed,
     collect({number: i.number, uid: i.uid, url: i.url}) AS closed
RETURN w.uid AS uid, w.kind AS kind, w.number AS number, w.title AS title, w.state AS state,
       w.url AS url, w.created_at AS created_at, w.closed_at AS closed_at, via, author,
       [x IN reviewed WHERE x.login IS NOT NULL] AS reviewers,
       [x IN closed WHERE x.uid IS NOT NULL] AS closes, s.uid AS system_uid
ORDER BY coalesce(w.closed_ts, w.created_ts) DESC
