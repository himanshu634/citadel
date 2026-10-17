// purpose: One person at a glance: teams, the systems they changed most (with last activity),
//          their recent PRs, the PRs they reviewed, and what they own by declaration.
//          Looked up by uid ("person:<login>", lower-case) so login case does not matter.
// params:  $person_uid, $limit (int, per list)
// returns: login, person_uid, display_name, is_bot, teams, systems ([{system, changes,
//          last_ts}]), prs_authored, recent_prs ([{uid, number, title, url, state}]), reviews_given,
//          recent_reviews ([{uid, number, title, url, state}]), owns. collect() keeps a map of
//          nulls from an OPTIONAL MATCH that found nothing, so the lists drop rows without a uid.
// example: make query TOOL=person_profile P="login=erin"
MATCH (p:Person {uid: $person_uid})
OPTIONAL MATCH (p)-[:MEMBER_OF]->(t:Team)
WITH p, collect(DISTINCT t.name) AS teams
OPTIONAL MATCH (p)-[:AUTHORED]->(c:Change)-[:TOUCHES]->(s:System)
WITH p, teams, s.name AS system, count(c) AS changes, max(c.ts) AS last_ts
ORDER BY changes DESC
WITH p, teams,
     [x IN collect({system: system, changes: changes, last_ts: last_ts})
      WHERE x.system IS NOT NULL][0..$limit] AS systems
OPTIONAL MATCH (p)-[:AUTHORED]->(pr:WorkItem {kind: 'pull_request'})
WITH p, teams, systems, pr ORDER BY pr.created_ts DESC
WITH p, teams, systems, count(pr) AS prs_authored,
     [x IN collect({uid: pr.uid, number: pr.number, title: pr.title, url: pr.url, state: pr.state})
      WHERE x.uid IS NOT NULL][0..$limit] AS recent_prs
OPTIONAL MATCH (p)-[rv:REVIEWED]->(rw:WorkItem)
WITH p, teams, systems, prs_authored, recent_prs, rw, rv ORDER BY rv.ts DESC
WITH p, teams, systems, prs_authored, recent_prs, count(rw) AS reviews_given,
     [x IN collect({uid: rw.uid, number: rw.number, title: rw.title, url: rw.url, state: rv.state})
      WHERE x.uid IS NOT NULL][0..$limit] AS recent_reviews
OPTIONAL MATCH (p)-[:OWNS]->(os:System)
RETURN p.login AS login, p.uid AS person_uid, p.display_name AS display_name,
       p.is_bot AS is_bot, teams, systems, prs_authored, recent_prs, reviews_given,
       recent_reviews, collect(DISTINCT os.name) AS owns
