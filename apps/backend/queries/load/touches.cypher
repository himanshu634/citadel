// purpose: (Change)-[:TOUCHES {files}]->(System): which code areas a commit changed, and the
//          files in each. This edge is what expertise ("who knows this system?") is derived from.
// params:  $rows: [{change_uid, system_uid, files}]
// returns: n (edges ensured)
// example: loader.load(...) runs it after Change and System nodes
UNWIND $rows AS row
MATCH (c:Change {uid: row.change_uid})
MATCH (s:System {uid: row.system_uid})
MERGE (c)-[t:TOUCHES]->(s)
SET t.files = row.files
RETURN count(t) AS n
