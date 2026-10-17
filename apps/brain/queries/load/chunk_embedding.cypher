// purpose: Store chunk vectors, with the text hash and model they were made from, so the embed
//          stage can tell which chunks changed since. A chunk written without a text_hash (by
//          backfill_body_chunks, or before chunks carried one) gets the hash it was embedded from.
// params:  $model, $rows: [{uid, vector, text_hash}] (text_hash as read by chunks_to_embed: a
//          text edited meanwhile keeps a different hash and is embedded again next run)
// returns: n (chunks written; a chunk deleted meanwhile is dropped)
// example: loader.set_embeddings("synthetic", rows, "BAAI/bge-base-en-v1.5")
UNWIND $rows AS row
MATCH (c:Chunk {uid: row.uid})
SET c.embedding = vecf32(row.vector),
    c.embedded_hash = row.text_hash,
    c.text_hash = coalesce(c.text_hash, row.text_hash),
    c.embed_model = $model
RETURN count(c) AS n
