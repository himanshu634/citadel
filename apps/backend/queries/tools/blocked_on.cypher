// purpose: What is a person waiting on? For each open ticket assigned to them, every open
//          blocker up to three BLOCKS hops away (shortest depth per pair). Every ticket on the
//          chain must be open, so a done or canceled ticket ends it. `via` is the key of the
//          next ticket on the way (null when the blocker is direct). Blockers come with their
//          assignees and the PRs/issues they mention (anything that is not a ticket).
// params:  $person_uid ("person:<login>"), $limit (int, rows)
// returns: person_uid, ticket and blocker ({uid, key, title, url, status_category, assignees}),
//          depth, via, linked ([{uid, number, title, url, state}]); sorted by ticket key, depth,
//          blocker key
// example: make query TOOL=blocked_on P="login=carol"
MATCH (p:Person {uid: $person_uid})-[:ASSIGNED_TO]->(t:WorkItem {kind: 'ticket'})
WHERE t.status_category IS NOT NULL AND NOT t.status_category IN ['done', 'canceled']
MATCH path = (b:WorkItem {kind: 'ticket'})-[:BLOCKS*1..3]->(t)
WHERE ALL(n IN nodes(path) WHERE n.status_category IS NOT NULL
                                 AND NOT n.status_category IN ['done', 'canceled'])
WITH p, t, b, path
ORDER BY length(path), nodes(path)[1].key
WITH p, t, b, collect(path)[0] AS best
WITH p, t, b, length(best) AS depth, nodes(best)[1].key AS via_key
OPTIONAL MATCH (b)-[:MENTIONS]->(x:WorkItem)
WHERE x.kind <> 'ticket'
WITH p, t, b, depth, via_key,
     collect(CASE WHEN x IS NULL THEN NULL ELSE {
       uid: x.uid, number: x.number, title: x.title, url: x.url, state: x.state} END) AS linked
RETURN p.uid AS person_uid,
       {uid: t.uid, key: t.key, title: t.title, url: t.url, status_category: t.status_category,
        assignees: [(t)<-[:ASSIGNED_TO]-(tp:Person) | tp.login]} AS ticket,
       {uid: b.uid, key: b.key, title: b.title, url: b.url, status_category: b.status_category,
        assignees: [(b)<-[:ASSIGNED_TO]-(bp:Person) | bp.login]} AS blocker,
       depth, CASE WHEN depth = 1 THEN NULL ELSE via_key END AS via, linked
ORDER BY t.key, depth, b.key
LIMIT $limit
