// purpose: The next chunks the embed stage must embed: never embedded, text changed since
//          (text_hash differs from embedded_hash), cleared by `brain embed --all`
//          (embedded_hash is null), or embedded by another model. Chunks with no text are left
//          out: there is nothing to embed. So is bot text (a comment by, or the body of a work
//          item authored by, a Person with is_bot = true): coverage reports and dependency
//          bumps are long boilerplate that would crowd out what people wrote.
// params:  $model (the embedder's model name), $limit (batch size)
// returns: uid, text, text_hash (null on chunks written before chunks carried one), by uid
// notes:   `embedded_hash IS NULL` is spelled out because `null <> x` is null, not true.
//          semantic_search applies the same bot rule, for vectors written before it.
// example: embeddings.embed_pending("synthetic") reads it once per batch
MATCH (c:Chunk)
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
