// purpose: chunks_to_embed limited to the chunks of some work items or documents: the
//          Archivist embeds what it just loaded, not the company's whole backlog. Same pending,
//          empty-text and bot rules as chunks_to_embed. The sources are found through the
//          Node.uid index, then their chunks: not a scan of every chunk.
// params:  $model (the embedder's model name), $limit (batch size), $sources (WorkItem or
//          Document uids)
// returns: uid, text, text_hash (null on chunks written before chunks carried one), by uid
// example: embeddings.embed_pending("synthetic", sources=["github:a/b:issue:812"])
MATCH (s:Node)
WHERE s.uid IN $sources
MATCH (c:Chunk)-[:FROM]->(s)
WHERE trim(coalesce(c.text, '')) <> ''
  AND (c.embedding IS NULL
       OR c.embedded_hash IS NULL
       OR c.embedded_hash <> c.text_hash
       OR c.embed_model IS NULL
       OR c.embed_model <> $model)
OPTIONAL MATCH (commenter:Person {uid: c.author_uid})
WITH c, commenter
WHERE coalesce(commenter.is_bot, false) = false
  AND NOT (c.kind = 'work_item'
           AND (c)-[:FROM]->(:WorkItem)<-[:AUTHORED]-(:Person {is_bot: true}))
RETURN c.uid AS uid, c.text AS text, c.text_hash AS text_hash
ORDER BY uid
LIMIT $limit
