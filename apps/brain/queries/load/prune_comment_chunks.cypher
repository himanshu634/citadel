// purpose: Delete the chunks a shorter comment no longer has: a comment now cut into `keep`
//          chunks loses the ones numbered `keep` and above. Runs after comment_chunk.
// params:  $rows: [{work_item_uid, comment_uid, keep}] (keep = how many chunks this load wrote
//          for that comment)
// returns: n (comments checked; rows whose work item is missing are dropped)
// notes:   Starts from the work item (its uid is indexed) and walks FROM, because comment_uid
//          has no index: matching chunks by it would scan every chunk once per row.
// example: loader.load(...) runs it after comment_chunk
UNWIND $rows AS row
MATCH (w:WorkItem {uid: row.work_item_uid})
OPTIONAL MATCH (c:Chunk {kind: 'comment'})-[:FROM]->(w)
WHERE c.comment_uid = row.comment_uid AND c.idx >= row.keep
DETACH DELETE c
RETURN count(DISTINCT row.comment_uid) AS n
