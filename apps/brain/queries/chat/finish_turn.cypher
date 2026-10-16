// purpose: Close a turn: its status (done, stopped, failed), the answer as the Ask page shows
//          it, its trace id (thumbs) and timing; the thread moves to the top of the chat list.
//          Each cited source becomes a CITED link to its Ref.
// params:  $thread_id, $turn, $status, $at, $ms, $error, $stop, $model, $trace_id,
//          $answer_json, $cited: [{uid, label, title, url}]
// returns: n (sources linked)
// example: history.Recorder(...).on({"kind": "answer", ...})
MATCH (t:Thread {id: $thread_id})-[:HAS_TURN]->(u:Turn {uid: $turn})
SET u.status = $status,
    u.ended_at = $at,
    u.ms = $ms,
    u.error = $error,
    u.stop = $stop,
    u.model = $model,
    u.trace_id = $trace_id,
    u.answer_json = $answer_json,
    t.updated_at = $at,
    t.last_status = $status
WITH u
UNWIND $cited AS ref
MERGE (r:Ref {uid: ref.uid})
SET r.label = coalesce(ref.label, r.label),
    r.title = coalesce(ref.title, r.title),
    r.url = coalesce(ref.url, r.url)
MERGE (u)-[:CITED]->(r)
RETURN count(r) AS n
