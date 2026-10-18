// purpose: Find PRs, issues, tickets, threads and documents whose text means the same as the
//          question, even in other words: nearest Chunk vectors (comments, work-item bodies,
//          document passages), then the WorkItem or Document each chunk comes FROM, keeping its
//          best chunk, then one hop out to the author and the systems it touches or mentions.
//          tools.py embeds the question with the same model as the chunks.
// params:  $vector (the question's embedding, list of floats), $k (nearest chunks to fetch),
//          $kinds (list of chunk kinds 'comment' / 'work_item' / 'document', or null for all),
//          $model (the embedder's model: vectors from another model are not comparable),
//          $limit (int, rows)
// returns: uid (the source WorkItem / Document), label, kind (the WorkItem's kind:
//          pull_request / issue / ticket / thread; 'document' for a Document), number, title,
//          state, url, chunk_uid, chunk_kind, snippet (first 300 chars of the best chunk),
//          similarity (0..1, higher is closer), author, systems
// notes:   The index is cosine, and its `score` is a cosine DISTANCE (a chunk's own vector
//          scores 0.0), so similarity = 1 - score, clamped to 0..1. $kinds filters after the
//          nearest-neighbour step, so tools.py asks for k = 200 when $kinds is set; otherwise
//          the many comment chunks could crowd out every document. The best chunk is picked
//          by reduce (lowest score, then lowest uid), not by collect order, which is not
//          guaranteed; ties between sources fall back to uid too. The author is min(login), so
//          a source with two AUTHORED edges is still one row. Bot text (a comment by, or the
//          body of a work item authored by, a Person with is_bot = true) is never returned, as
//          chunks_to_embed never embeds it; this also hides vectors written before that rule.
//          Like $kinds it filters after the nearest-neighbour step, as does $model; when the
//          search returns nothing, tools.py asks embedded_models why. Never returns a vector.
// example: make query TOOL=semantic_search P="text='why do invoices get charged twice'"
CALL db.idx.vector.queryNodes('Chunk', 'embedding', $k, vecf32($vector)) YIELD node, score
WITH node AS c, score
WHERE c.embed_model = $model AND ($kinds IS NULL OR c.kind IN $kinds)
OPTIONAL MATCH (commenter:Person {uid: c.author_uid})
WITH c, score, commenter
WHERE coalesce(commenter.is_bot, false) = false
MATCH (c)-[:FROM]->(src)
WHERE NOT (c.kind = 'work_item' AND (src)<-[:AUTHORED]-(:Person {is_bot: true}))
WITH src, collect({chunk: c, uid: c.uid, score: score}) AS hits
WITH src, reduce(best = null, h IN hits |
       CASE WHEN best IS NULL OR h.score < best.score
                 OR (h.score = best.score AND h.uid < best.uid)
            THEN h ELSE best END) AS best
WITH src, best.chunk AS c, best.score AS score
ORDER BY score ASC, src.uid ASC
LIMIT $limit
OPTIONAL MATCH (a:Person)-[:AUTHORED]->(src)
WITH src, c, score, min(a.login) AS author
OPTIONAL MATCH (src)<-[:PART_OF]-(:Change)-[:TOUCHES]->(ts:System)
WITH src, c, score, author, collect(DISTINCT ts.name) AS touched
OPTIONAL MATCH (src)-[:MENTIONS]->(ms:System)
WITH src, c, score, author, touched, collect(DISTINCT ms.name) AS mentioned
RETURN src.uid AS uid,
       head([l IN labels(src) WHERE l <> 'Node']) AS label,
       CASE WHEN 'Document' IN labels(src) THEN 'document' ELSE src.kind END AS kind,
       src.number AS number, src.title AS title, src.state AS state, src.url AS url,
       c.uid AS chunk_uid, c.kind AS chunk_kind, left(c.text, 300) AS snippet,
       CASE WHEN score > 1.0 THEN 0.0 WHEN score < 0.0 THEN 1.0 ELSE 1.0 - score END
         AS similarity,
       author, touched + [x IN mentioned WHERE NOT x IN touched] AS systems
ORDER BY similarity DESC, uid ASC
