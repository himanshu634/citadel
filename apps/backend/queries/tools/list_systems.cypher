// purpose: The company's systems (code areas) with how much work touches them, so a person or
//          an agent can turn "the indexing code" into an exact System name for the other tools.
// params:  $limit (int)
// returns: system, system_uid, path_rule, changes, people (distinct human authors), owners
// example: make query TOOL=list_systems
MATCH (s:System)
OPTIONAL MATCH (p:Person)-[:AUTHORED]->(c:Change)-[:TOUCHES]->(s)
WITH s, count(c) AS changes,
     count(DISTINCT CASE WHEN p.is_bot = false THEN p END) AS people
OPTIONAL MATCH (o)-[:OWNS]->(s)
RETURN s.name AS system, s.uid AS system_uid, s.path_rule AS path_rule, changes, people,
       collect(DISTINCT coalesce(o.name, o.login)) AS owners
ORDER BY changes DESC, system
LIMIT $limit
