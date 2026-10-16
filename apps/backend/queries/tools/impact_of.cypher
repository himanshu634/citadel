// purpose: What else is affected if this system changes? Systems that are changed in the same
//          commits as this one (co-change), ranked by how often. coupling = co-changes divided
//          by all changes to this system. For each, the people who work there (top human
//          authors) and its declared owners: the people to tell before changing it.
// params:  $system (System name), $limit (int)
// returns: system, system_uid, co_changes, coupling, examples (commit urls), people, owners
// example: make query TOOL=impact_of P="system=Billing"
MATCH (s:System {name: $system})<-[:TOUCHES]-(all:Change)
WITH s, count(all) AS total
MATCH (s)<-[:TOUCHES]-(c:Change)-[:TOUCHES]->(other:System)
WHERE other <> s
WITH other, total, count(c) AS co_changes, collect(c.url)[0..3] AS examples
ORDER BY co_changes DESC
LIMIT $limit
OPTIONAL MATCH (p:Person)-[:AUTHORED]->(pc:Change)-[:TOUCHES]->(other)
WHERE p.is_bot = false
WITH other, total, co_changes, examples, p.login AS login, count(pc) AS n
ORDER BY n DESC
WITH other, total, co_changes, examples,
     [x IN collect({login: login, changes: n}) WHERE x.login IS NOT NULL][0..3] AS people
OPTIONAL MATCH (o)-[:OWNS]->(other)
RETURN other.name AS system, other.uid AS system_uid, co_changes,
       round(1000.0 * co_changes / total) / 1000.0 AS coupling, examples, people,
       collect(DISTINCT coalesce(o.name, o.login)) AS owners
ORDER BY co_changes DESC
