// purpose: Open a turn: create the thread on its first question (titled by it), number the new
//          turn after the thread's last one and mark both as running.
// params:  $thread_id, $title, $question, $at (epoch ms)
// returns: uid ("<thread_id>:<n>"), n
// notes:   One run per thread at a time (the Ask API's claim), so turn_count cannot race.
// example: history.Recorder(store, "Why JWT?").on({"kind": "start", "thread_id": "abc"})
MERGE (t:Thread {id: $thread_id})
ON CREATE SET t.title = $title, t.created_at = $at, t.turn_count = 0
SET t.turn_count = t.turn_count + 1, t.updated_at = $at, t.last_status = 'running'
CREATE (t)-[:HAS_TURN]->(u:Turn {
    uid: $thread_id + ':' + toString(t.turn_count),
    thread_id: $thread_id,
    n: t.turn_count,
    question: $question,
    status: 'running',
    started_at: $at
})
RETURN u.uid AS uid, u.n AS n
