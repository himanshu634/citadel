// purpose: Where does declared ownership disagree with reality? For every system that has a
//          declared owner (CODEOWNERS), compare the owners (owning people, and members of
//          owning teams) with the top human contributors since $since_ts. A row is returned
//          when the #1 contributor is not among the owners. If an owning team has no known
//          members (GitHub team membership is often not public), members_known is false and
//          the mismatch only means "we cannot confirm the owner team does this work".
// params:  $since_ts (epoch seconds, 0 = all), $top (how many top contributors to list)
// returns: system, system_uid, declared_owners, owner_people, members_known, top_contributors
//          ([{login, changes}]), top_is_owner (always false here), total_changes
// example: make query TOOL=owners_vs_experts
MATCH (o)-[:OWNS]->(s:System)
WITH s, collect(DISTINCT o) AS owners
UNWIND owners AS o
OPTIONAL MATCH (m:Person)-[:MEMBER_OF]->(o)
WITH s, owners, collect(DISTINCT m.login) AS team_members
WITH s,
     [x IN owners | coalesce(x.name, x.login)] AS declared_owners,
     team_members + [x IN owners WHERE x:Person | x.login] AS owner_people,
     size(team_members) > 0 OR all(x IN owners WHERE x:Person) AS members_known
MATCH (p:Person)-[:AUTHORED]->(c:Change)-[:TOUCHES]->(s)
WHERE p.is_bot = false AND c.ts >= $since_ts
WITH s, declared_owners, owner_people, members_known, p.login AS login, count(c) AS n
ORDER BY n DESC
WITH s, declared_owners, owner_people, members_known,
     collect({login: login, changes: n}) AS ranked, sum(n) AS total_changes
WHERE NOT ranked[0].login IN owner_people
RETURN s.name AS system, s.uid AS system_uid, declared_owners, owner_people, members_known,
       ranked[0..$top] AS top_contributors, total_changes
ORDER BY total_changes DESC
