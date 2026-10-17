// purpose: Who works most closely together? Pairs of people ranked by the PRs one of them
//          reviewed of the other's (either way round). `shared_threads` counts the issues,
//          tickets and chat threads both commented on; it is shown, not ranked, because a
//          maintainer who comments on everything would top every pair. With $person_uid only
//          that person's pairs, that person first. Bots are left out.
// params:  $person_uid (string or null = everyone), $since_ts (epoch seconds of the review,
//          0 = all), $limit (int)
// returns: people ([{login, person_uid}] x2), reviews (distinct PRs), a_reviewed_b (PRs of the
//          second person the first reviewed), b_reviewed_a, shared_threads, examples (latest
//          reviewed PRs, [{uid, number, title, url}]), shared_examples (latest shared threads)
// example: make query TOOL=collaborators P="limit=5"
MATCH (author:Person)-[:AUTHORED]->(pr:WorkItem {kind: 'pull_request'})<-[rv:REVIEWED]-(rev:Person)
WHERE author <> rev AND author.is_bot = false AND rev.is_bot = false
  AND coalesce(rv.ts, 0) >= $since_ts
  AND ($person_uid IS NULL OR author.uid = $person_uid OR rev.uid = $person_uid)
WITH author, rev, pr ORDER BY coalesce(pr.closed_ts, pr.created_ts) DESC
WITH CASE WHEN rev.uid = $person_uid OR ($person_uid IS NULL AND author.login > rev.login)
          THEN [rev, author] ELSE [author, rev] END AS pair, author, pr
WITH pair[0] AS a, pair[1] AS b,
     count(DISTINCT pr) AS reviews,
     count(DISTINCT CASE WHEN author = pair[1] THEN pr END) AS a_reviewed_b,
     collect(DISTINCT {uid: pr.uid, number: pr.number, title: pr.title, url: pr.url})[0..3]
       AS examples
OPTIONAL MATCH (a)-[:COMMENTED_ON]->(w:WorkItem)<-[:COMMENTED_ON]-(b)
WHERE w.kind <> 'pull_request'
WITH a, b, reviews, a_reviewed_b, examples, w
ORDER BY coalesce(w.closed_ts, w.created_ts) DESC
WITH a, b, reviews, a_reviewed_b, examples, count(DISTINCT w) AS shared_threads,
     collect(DISTINCT {uid: w.uid, number: w.number, title: w.title, url: w.url})
       AS shared
RETURN [{login: a.login, person_uid: a.uid}, {login: b.login, person_uid: b.uid}] AS people,
       reviews, a_reviewed_b, reviews - a_reviewed_b AS b_reviewed_a, shared_threads, examples,
       [x IN shared WHERE x.uid IS NOT NULL][0..2] AS shared_examples
ORDER BY reviews DESC, shared_threads DESC, a.login, b.login
LIMIT $limit
