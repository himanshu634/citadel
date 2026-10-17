// purpose: Which models the chunks of the graph are embedded with, so semantic search can say
//          why it found nothing: no chunk embedded yet, or every vector from another model.
// params:  none
// returns: model, n (chunks with a vector from that model), most first
// example: tools.semantic_search runs it when the search returns no rows
MATCH (c:Chunk)
WHERE c.embedding IS NOT NULL
RETURN c.embed_model AS model, count(c) AS n
ORDER BY n DESC, model ASC
