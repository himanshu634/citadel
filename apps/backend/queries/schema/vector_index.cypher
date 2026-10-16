// purpose: Vector (HNSW) index on Chunk embeddings, for semantic search over text chunks.
//          Cosine similarity, because text embedding models are compared by angle, not length.
// params:  {{EMBEDDING_DIM}} is a text placeholder, not a Cypher parameter: FalkorDB does not
//          accept parameters inside index OPTIONS. `brain schema` substitutes EMBEDDING_DIM from
//          env (an int) before running. The query text itself still lives only in this file.
// returns: nothing (indices_created count)
// notes:   The dimension must match the embedding model. To change it, drop the index first.
//          Query it with:
//          CALL db.idx.vector.queryNodes('Chunk', 'embedding', $k, vecf32($v)) YIELD node, score
// example: EMBEDDING_DIM=768 brain schema falkordb
CREATE VECTOR INDEX FOR (c:Chunk) ON (c.embedding) OPTIONS {dimension: {{EMBEDDING_DIM}}, similarityFunction: 'cosine'};
