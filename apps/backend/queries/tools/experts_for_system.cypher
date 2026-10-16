// purpose: Who knows this system? People ranked by their recent work in it: commits that touch
//          the system, plus reviews of PRs whose commits touch it. Expertise is derived from the
//          graph at query time (Person -> Change -> System), never stored, so it is always current.
//          Each event is weighted by recency (the weight halves every $half_life_days) and a
//          review counts $review_weight of a commit. Bots are excluded. Declared owners
//          (CODEOWNERS) are returned alongside, to compare "supposed to know" with "actually does".
// params:  $system (System name), $since_ts (epoch seconds, 0 = all), $now (epoch seconds),
//          $half_life_days (float), $review_weight (float), $limit (int)
// returns: login, person_uid, score, changes, reviews, last_active_ts, teams, is_declared_owner,
//          evidence (urls of their latest commits / reviewed PRs here), declared_owners, system_uid
// example: make query TOOL=experts_for_system P="system=Billing"
MATCH (s:System {name: $system})
OPTIONAL MATCH (o)-[:OWNS]->(s)
WITH s, collect(DISTINCT coalesce(o.name, o.login)) AS declared_owners
OPTIONAL MATCH (a:Person)-[:AUTHORED]->(c:Change)-[:TOUCHES]->(s)
WHERE a.is_bot = false AND c.ts >= $since_ts
WITH s, declared_owners,
     collect({login: a.login, kind: 'change', ts: c.ts, url: c.url}) AS authored
OPTIONAL MATCH (r:Person)-[rv:REVIEWED]->(w:WorkItem)<-[:PART_OF]-(:Change)-[:TOUCHES]->(s)
WHERE r.is_bot = false AND rv.ts >= $since_ts
WITH s, declared_owners, authored,
     collect(DISTINCT {login: r.login, kind: 'review', ts: rv.ts, url: w.url}) AS reviewed
UNWIND authored + reviewed AS ev
WITH s, declared_owners, ev
WHERE ev.login IS NOT NULL
WITH s, declared_owners, ev ORDER BY ev.ts DESC
WITH s, declared_owners, ev.login AS login,
     sum(CASE ev.kind WHEN 'change' THEN 1 ELSE 0 END) AS changes,
     sum(CASE ev.kind WHEN 'review' THEN 1 ELSE 0 END) AS reviews,
     sum((CASE ev.kind WHEN 'change' THEN 1.0 ELSE $review_weight END)
         * exp(-0.6931 * ($now - ev.ts) / ($half_life_days * 86400.0))) AS score,
     max(ev.ts) AS last_active_ts,
     collect(DISTINCT ev.url)[0..3] AS evidence
ORDER BY score DESC
LIMIT $limit
MATCH (p:Person {login: login})
OPTIONAL MATCH (p)-[:MEMBER_OF]->(t:Team)
WITH s, declared_owners, p, changes, reviews, score, last_active_ts, evidence,
     collect(DISTINCT t.name) AS teams
OPTIONAL MATCH (p)-[direct:OWNS]->(s)
WITH s, declared_owners, p, changes, reviews, score, last_active_ts, evidence, teams,
     count(direct) > 0 OR any(x IN teams WHERE x IN declared_owners) AS is_declared_owner
RETURN p.login AS login, p.uid AS person_uid, round(score * 1000) / 1000.0 AS score,
       toInteger(changes) AS changes, toInteger(reviews) AS reviews, last_active_ts, teams,
       is_declared_owner, evidence, declared_owners, s.uid AS system_uid
ORDER BY score DESC
