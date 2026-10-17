// purpose: Delete the body chunks a shorter work-item text no longer has: a body now cut into
//          `keep` chunks loses the ones numbered `keep` and above. Runs after work_item_chunk.
// params:  $rows: [{work_item_uid, keep}] (keep = how many chunks this load wrote for that item)
// returns: n (work items checked)
// example: loader.load(...) runs it after work_item_chunk
UNWIND $rows AS row
MATCH (w:WorkItem {uid: row.work_item_uid})
OPTIONAL MATCH (c:Chunk {kind: 'work_item'})-[:FROM]->(w)
WHERE c.idx >= row.keep
DETACH DELETE c
RETURN count(DISTINCT w) AS n
