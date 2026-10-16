// purpose: The next chunks the embed stage must embed: never embedded, text changed since
//          (text_hash differs from embedded_hash), cleared by `brain embed --all`
//          (embedded_hash is null), or embedded by another model. Chunks with no text are left
//          out: there is nothing to embed.
// params:  $model (the embedder's model name), $limit (batch size)
// returns: uid, text, text_hash (null on chunks written before chunks carried one), by uid
// notes:   `embedded_hash IS NULL` is spelled out because `null <> x` is null, not true.
// example: embeddings.embed_pending("synthetic") reads it once per batch
MATCH (c:Chunk)
WHERE trim(coalesce(c.text, '')) <> ''
  AND (c.embedding IS NULL
       OR c.embedded_hash IS NULL
       OR c.embedded_hash <> c.text_hash
       OR c.embed_model IS NULL
       OR c.embed_model <> $model)
RETURN c.uid AS uid, c.text AS text, c.text_hash AS text_hash
ORDER BY uid
LIMIT $limit
