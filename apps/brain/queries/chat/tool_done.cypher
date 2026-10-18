// purpose: A graph tool (or the answer check) has run: store its result on its ToolCall and
//          link it to a Ref for every uid it returned. A call no response announced is created
//          here, so no result is lost: the Archivist's calls inside an ask_archivist call (kind
//          'archive', $parent the outer call's id) arrive only this way.
// params:  $turn, $thread_id, $uid, $id, $tool, $kind, $parent (null but for 'archive'), $n,
//          $input_json, $status, $error, $ms, $count, $rows_json, $nodes_json, $rels_json,
//          $refs: [{uid, label, title, url}]
// returns: n (refs linked)
// example: history.Recorder(...).on({"kind": "step_done", "id": "toolu_1", ...})
MERGE (c:ToolCall {uid: $uid})
ON CREATE SET c.id = $id, c.thread_id = $thread_id, c.turn = $turn, c.tool = $tool,
              c.kind = $kind, c.input_json = $input_json
SET c.parent = $parent,
    c.n = $n,
    c.status = $status,
    c.error = $error,
    c.ms = $ms,
    c.count = $count,
    c.rows_json = $rows_json,
    c.nodes_json = $nodes_json,
    c.rels_json = $rels_json
WITH c
UNWIND $refs AS ref
MERGE (r:Ref {uid: ref.uid})
SET r.label = coalesce(ref.label, r.label),
    r.title = coalesce(ref.title, r.title),
    r.url = coalesce(ref.url, r.url)
MERGE (c)-[:TOUCHED]->(r)
RETURN count(r) AS n
