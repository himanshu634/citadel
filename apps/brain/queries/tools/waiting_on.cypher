// purpose: Who is waiting on a person? Other people's open tickets that are blocked directly by
//          one of the person's open tickets. Tickets assigned to the person are left out.
// params:  $person_uid ("person:<login>"), $limit (int, rows)
// returns: person_uid, mine ({uid, key, title, url, status_category, assignees}), waiting (same
//          shape); one row per pair, sorted by the person's ticket key then the waiting key
// example: make query TOOL=waiting_on P="login=alice"
MATCH (p:Person {uid: $person_uid})-[:ASSIGNED_TO]->(m:WorkItem {kind: 'ticket'})
WHERE m.status_category IS NOT NULL AND NOT m.status_category IN ['done', 'canceled']
MATCH (m)-[:BLOCKS]->(w:WorkItem)
WHERE w.status_category IS NOT NULL AND NOT w.status_category IN ['done', 'canceled']
  AND NOT (p)-[:ASSIGNED_TO]->(w)
RETURN p.uid AS person_uid,
       {uid: m.uid, key: m.key, title: m.title, url: m.url, status_category: m.status_category,
        assignees: [(m)<-[:ASSIGNED_TO]-(mp:Person) | mp.login]} AS mine,
       {uid: w.uid, key: w.key, title: w.title, url: w.url, status_category: w.status_category,
        assignees: [(w)<-[:ASSIGNED_TO]-(wp:Person) | wp.login]} AS waiting
ORDER BY m.key, w.key
LIMIT $limit
