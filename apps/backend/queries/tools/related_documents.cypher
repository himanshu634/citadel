// purpose: Find design docs, ADRs, READMEs and runbooks about a topic: full-text search over
//          Document titles and bodies (RediSearch, TF-IDF score), plus the systems and work
//          items each document mentions. $query is a RediSearch query string; tools.py turns
//          plain text into "word1|word2|..." (any word matches, best matches first).
//          Long documents often get a full-text score of ~0, so ties are broken by how many
//          of the query words appear in the document's title or path (title_hits).
// params:  $query (RediSearch query), $words (the same words, lower-case list), $limit (int)
// returns: uid, title, path, url, snippet (first 300 chars), score, title_hits, updated_at, systems,
//          mentions ([{number, uid}])
// example: make query TOOL=related_documents P="text='managed postgres backups'"
CALL db.idx.fulltext.queryNodes('Document', $query) YIELD node, score
WITH node AS d, score
WITH d, score, size([w IN $words WHERE toLower(d.title + ' ' + d.path) CONTAINS w]) AS title_hits
ORDER BY score DESC, title_hits DESC
LIMIT $limit
OPTIONAL MATCH (d)-[:MENTIONS]->(s:System)
WITH d, score, title_hits, collect(DISTINCT s.name) AS systems
OPTIONAL MATCH (d)-[:MENTIONS]->(w:WorkItem)
WITH d, score, title_hits, systems, collect(DISTINCT {number: w.number, uid: w.uid}) AS mentioned
RETURN d.uid AS uid, d.title AS title, d.path AS path, d.url AS url,
       left(d.body, 300) AS snippet, score, title_hits,
       d.updated_at AS updated_at, systems,
       [x IN mentioned WHERE x.uid IS NOT NULL] AS mentions
ORDER BY score DESC, title_hits DESC
