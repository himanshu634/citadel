// purpose: Noticing, stale_owner: systems whose declared owners (CODEOWNERS) do not include the
//          person doing most of the work. The same logic as tools/owners_vs_experts, over all
//          time, returning uids so the Keeper can open a gap about the system and the person.
// params:  $limit (int)
// returns: subject (system uid), system (name), declared_owners ([name]), members_known,
//          person_uid, login, changes (theirs), total_changes (both integers); most active
//          systems first
// example: keeper.notice("synthetic", "stale_owner", 10)
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
WHERE p.is_bot = false
WITH s, declared_owners, owner_people, members_known, p, count(c) AS n
ORDER BY n DESC, p.login
WITH s, declared_owners, owner_people, members_known,
     collect({uid: p.uid, login: p.login, changes: n}) AS ranked, sum(n) AS total_changes
WHERE NOT ranked[0].login IN owner_people
RETURN s.uid AS subject, s.name AS system, declared_owners, members_known,
       ranked[0].uid AS person_uid, ranked[0].login AS login,
       toInteger(ranked[0].changes) AS changes, toInteger(total_changes) AS total_changes
ORDER BY total_changes DESC, subject
LIMIT $limit
