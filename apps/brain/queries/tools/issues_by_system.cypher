// purpose: Which systems (modules, code areas) have the most issues? Per system: the issues and
//          tickets whose text names a path in it (`mentioned`, the ranking), and apart from
//          those the ones closed by a PR whose commits changed it (`fixed_in`, the tie-break: a
//          fix PR also touches the tests, so this count runs high on test folders). `issues`,
//          `open` and `closed` cover both; a ticket is open until its status_category is done
//          or canceled. Issues opened by bots are left out. With $state only issues in that
//          state count.
// params:  $state ('open' | 'closed' | null = both), $limit (int)
// returns: system, system_uid, issues, open, closed, mentioned, fixed_in, examples (latest
//          issues, mentioned first, [{uid, number, title, url, state}])
// example: make query TOOL=issues_by_system P="limit=5"
MATCH (s:System)
OPTIONAL MATCH (m:WorkItem)-[:MENTIONS]->(s)
WHERE m.kind IN ['issue', 'ticket']
  AND ($state IS NULL OR $state =
       CASE WHEN coalesce(NOT m.status_category IN ['done', 'canceled'], m.state = 'open')
            THEN 'open' ELSE 'closed' END)
  AND NOT (m)<-[:AUTHORED]-(:Person {is_bot: true})
WITH s, m ORDER BY coalesce(m.closed_ts, m.created_ts) DESC
WITH s, collect(DISTINCT m) AS mentioned
OPTIONAL MATCH (s)<-[:TOUCHES]-(:Change)-[:PART_OF]->(:WorkItem)-[:CLOSES]->(f:WorkItem)
WHERE f.kind IN ['issue', 'ticket']
  AND ($state IS NULL OR $state =
       CASE WHEN coalesce(NOT f.status_category IN ['done', 'canceled'], f.state = 'open')
            THEN 'open' ELSE 'closed' END)
  AND NOT (f)<-[:AUTHORED]-(:Person {is_bot: true}) AND NOT f IN mentioned
WITH s, mentioned, f ORDER BY coalesce(f.closed_ts, f.created_ts) DESC
WITH s, mentioned, collect(DISTINCT f) AS fixed
WITH s, mentioned, fixed, mentioned + fixed AS issues
WHERE size(issues) > 0
WITH s, mentioned, fixed, issues,
     size([x IN issues WHERE coalesce(NOT x.status_category IN ['done', 'canceled'],
                                      x.state = 'open')]) AS open
RETURN s.name AS system, s.uid AS system_uid, size(issues) AS issues, open,
       size(issues) - open AS closed,
       size(mentioned) AS mentioned, size(fixed) AS fixed_in,
       [x IN issues[0..3] | {uid: x.uid, number: x.number, title: x.title, url: x.url,
                             state: x.state}] AS examples
ORDER BY mentioned DESC, fixed_in DESC, system
LIMIT $limit
