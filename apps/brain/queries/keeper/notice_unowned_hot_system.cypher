// purpose: Noticing, unowned_hot_system: systems with recent changes and no declared owner
//          (no OWNS), so nobody is on record to ask about them. Lists the busiest human author.
// params:  $since_ts (epoch seconds; keeper.notice passes now - 90 days), $limit (int)
// returns: subject (system uid), system (name), changes (since $since_ts), person_uid and login
//          of the human with most of those changes (null if only bots); busiest systems first
// example: keeper.notice("synthetic", "unowned_hot_system", 10)
MATCH (s:System)
OPTIONAL MATCH (o)-[:OWNS]->(s)
WITH s, count(o) AS owners
WHERE owners = 0
MATCH (c:Change)-[:TOUCHES]->(s)
WHERE c.ts >= $since_ts
WITH s, collect(c) AS recent
UNWIND recent AS c
OPTIONAL MATCH (p:Person)-[:AUTHORED]->(c)
WITH s, size(recent) AS changes, p, count(CASE WHEN p.is_bot = false THEN c END) AS n
ORDER BY n DESC, p.login
WITH s, changes, [x IN collect(CASE WHEN n > 0 THEN {uid: p.uid, login: p.login} END)
                  WHERE x IS NOT NULL] AS people
RETURN s.uid AS subject, s.name AS system, changes,
       people[0].uid AS person_uid, people[0].login AS login
ORDER BY changes DESC, subject
LIMIT $limit
