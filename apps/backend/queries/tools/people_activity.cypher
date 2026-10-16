// purpose: The people in a company with how many PRs they authored and how many PRs they
//          reviewed, busiest first. Bots are left out.
// params:  $limit (int)
// returns: login, name (display name), teams, prs (authored pull requests), reviews
//          (distinct PRs reviewed)
// example: make query TOOL=people_activity P="limit=8"
MATCH (p:Person)
WHERE p.is_bot = false
OPTIONAL MATCH (p)-[:MEMBER_OF]->(t:Team)
WITH p, collect(DISTINCT t.name) AS teams
OPTIONAL MATCH (p)-[:AUTHORED]->(pr:WorkItem {kind: 'pull_request'})
WITH p, teams, count(pr) AS prs
OPTIONAL MATCH (p)-[:REVIEWED]->(rw:WorkItem)
WITH p, teams, prs, count(rw) AS reviews
RETURN p.login AS login, p.display_name AS name, teams, prs, reviews
ORDER BY prs + reviews DESC, login
LIMIT $limit
