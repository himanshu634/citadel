// purpose: Find PRs, issues and threads about a topic: full-text search over WorkItem titles
//          and bodies (RediSearch, ranked by TF-IDF score), then one hop out to who wrote each
//          one, which systems its commits touched or its text mentions, and what it closes /
//          is closed by. $query is a RediSearch query string; tools.py turns plain text into
//          "word1|word2|..." (any word matches, best matches score highest).
// params:  $query (RediSearch query), $limit (int)
// returns: uid, kind, number, title, state, url, score, author, systems, closes, closed_by
// example: make query TOOL=related_work_items P="text='invoice batch duplicate'"
CALL db.idx.fulltext.queryNodes('WorkItem', $query) YIELD node, score
WITH node AS w, score
ORDER BY score DESC
LIMIT $limit
OPTIONAL MATCH (a:Person)-[:AUTHORED]->(w)
WITH w, score, a.login AS author
OPTIONAL MATCH (w)<-[:PART_OF]-(:Change)-[:TOUCHES]->(ts:System)
WITH w, score, author, collect(DISTINCT ts.name) AS touched
OPTIONAL MATCH (w)-[:MENTIONS]->(ms:System)
WITH w, score, author, touched, collect(DISTINCT ms.name) AS mentioned
OPTIONAL MATCH (w)-[:CLOSES]->(closed:WorkItem)
WITH w, score, author, touched, mentioned,
     collect(DISTINCT {number: closed.number, uid: closed.uid}) AS closes
OPTIONAL MATCH (closer:WorkItem)-[:CLOSES]->(w)
WITH w, score, author, touched, mentioned, closes,
     collect(DISTINCT {number: closer.number, uid: closer.uid}) AS closed_by
RETURN w.uid AS uid, w.kind AS kind, w.number AS number, w.title AS title, w.state AS state,
       w.url AS url, score, author,
       touched + [x IN mentioned WHERE NOT x IN touched] AS systems,
       [x IN closes WHERE x.uid IS NOT NULL] AS closes,
       [x IN closed_by WHERE x.uid IS NOT NULL] AS closed_by
ORDER BY score DESC
