// purpose: Mark every chunk as pending for the embed stage (`brain embed --all`). The vectors
//          stay until they are replaced, so search keeps working while the stage runs.
// params:  none
// returns: n (chunks marked)
// example: loader.clear_embedded("synthetic"), then embeddings.embed_pending runs as usual
MATCH (c:Chunk)
SET c.embedded_hash = NULL
RETURN count(c) AS n
