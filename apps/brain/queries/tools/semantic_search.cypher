// purpose: Find PRs, issues, tickets, threads and documents whose text means the same as the
//          question, even in other words: nearest Chunk vectors (comments, work-item bodies,
//          document passages), then the WorkItem or Document each chunk comes FROM, keeping its
//          best chunk, then one hop out to the author and the systems it touches or mentions.
//          tools.py embeds the question with the same model as the chunks.
// params:  $vector (the question's embedding, list of floats), $k (nearest chunks to fetch),
//          $kinds (list of chunk kinds 'comment' / 'work_item' / 'document', or null for all),
//          $limit (int, rows)
// returns: uid (the source WorkItem / Document), label, kind (the WorkItem's kind: pull_request /
//          issue / ticket / thread; 'document' for a Document), number, title, state, url, chunk_uid, chunk_kind, snippet (first 300
//          chars of the best chunk), similarity (0..1, higher is closer), author, systems
// notes:   The index is cosine, and its `score` is a cosine DISTANCE (a chunk's own vector
//          scores 0.0), so similarity = 1 - score, floored at 0. $kinds filters after the
//          nearest-neighbour step, so tools.py asks for k = 200 when $kinds is set; otherwise
//          the many comment chunks could crowd out every document. The author is collected so a
//          source with two AUTHORED edges is still one row. Never returns a vector.
// example: make query TOOL=semantic_search P="text='why do invoices get charged twice'"
CALL db.idx.vector.queryNodes('Chunk', 'embedding', $k, vecf32($vector)) YIELD node, score
WITH node AS c, score
WHERE $kinds IS NULL OR c.kind IN $kinds
MATCH (c)-[:FROM]->(src)
WITH src, c, score
ORDER BY score ASC
WITH src, collect({chunk: c, score: score})[0] AS best
WITH src, best.chunk AS c, best.score AS score
ORDER BY score ASC
LIMIT $limit
OPTIONAL MATCH (a:Person)-[:AUTHORED]->(src)
WITH src, c, score, collect(a.login)[0] AS author
OPTIONAL MATCH (src)<-[:PART_OF]-(:Change)-[:TOUCHES]->(ts:System)
WITH src, c, score, author, collect(DISTINCT ts.name) AS touched
OPTIONAL MATCH (src)-[:MENTIONS]->(ms:System)
WITH src, c, score, author, touched, collect(DISTINCT ms.name) AS mentioned
RETURN src.uid AS uid, labels(src)[0] AS label,
       CASE WHEN 'Document' IN labels(src) THEN 'document' ELSE src.kind END AS kind,
       src.number AS number, src.title AS title, src.state AS state, src.url AS url,
       c.uid AS chunk_uid, c.kind AS chunk_kind, left(c.text, 300) AS snippet,
       CASE WHEN 1.0 - score < 0 THEN 0.0 ELSE 1.0 - score END AS similarity, author,
       touched + [x IN mentioned WHERE NOT x IN touched] AS systems
ORDER BY similarity DESC
