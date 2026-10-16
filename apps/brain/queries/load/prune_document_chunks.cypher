// purpose: Delete the chunks a shorter document no longer has: a document now cut into `keep`
//          chunks loses the ones numbered `keep` and above. Runs after document_chunk.
// params:  $rows: [{doc_uid, keep}] (keep = how many chunks this load wrote for that document)
// returns: n (documents checked)
// example: loader.load(...) runs it after document_chunk
UNWIND $rows AS row
MATCH (d:Document {uid: row.doc_uid})
OPTIONAL MATCH (c:Chunk {kind: 'document'})-[:FROM]->(d)
WHERE c.idx >= row.keep
DETACH DELETE c
RETURN count(DISTINCT d) AS n
