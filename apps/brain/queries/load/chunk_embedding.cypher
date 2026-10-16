// purpose: Store chunk vectors, with the text hash and model they were made from, so the embed
//          stage can tell which chunks changed since.
// params:  $model, $rows: [{uid, vector, text_hash}] (text_hash as read by chunks_to_embed: a
//          text edited meanwhile keeps a different hash and is embedded again next run)
// returns: n (chunks written; a chunk deleted meanwhile is dropped)
// example: loader.set_embeddings("synthetic", rows, "BAAI/bge-base-en-v1.5")
UNWIND $rows AS row
MATCH (c:Chunk {uid: row.uid})
SET c.embedding = vecf32(row.vector),
    c.embedded_hash = row.text_hash,
    c.embed_model = $model
RETURN count(c) AS n
