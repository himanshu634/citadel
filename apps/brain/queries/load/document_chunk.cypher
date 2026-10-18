// purpose: Store a document (title first) as one or more Chunks FROM it, cut by chunking.split_text,
//          so semantic search finds the passage that matches, not only the whole file. `idx` is the
//          chunk's position, which prune_document_chunks uses when a document shrinks.
// params:  $company, $rows: [{uid, document_uid, idx, text, text_hash, ts, source, url}]
// returns: n (chunks written; rows whose document is missing are dropped)
// example: loader.load(...) runs it after Document nodes
UNWIND $rows AS row
MATCH (d:Document {uid: row.document_uid})
MERGE (c:Chunk {uid: row.uid})
SET c:Node,
    c.company = $company,
    c.kind = 'document',
    c.idx = row.idx,
    c.text = row.text,
    c.text_hash = row.text_hash,
    c.ts = row.ts,
    c.source = row.source,
    c.url = row.url
MERGE (c)-[:FROM]->(d)
RETURN count(c) AS n
