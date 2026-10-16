// purpose: A thread's turns in order.
// params:  $id
// returns: uid, n, question, status, started_at, ended_at, ms, error, stop, model, trace_id,
//          answer_json
// example: GET /api/companies/synthetic/threads/abc123
MATCH (u:Turn {thread_id: $id})
RETURN u.uid AS uid, u.n AS n, u.question AS question, u.status AS status,
       u.started_at AS started_at, u.ended_at AS ended_at, u.ms AS ms, u.error AS error,
       u.stop AS stop, u.model AS model, u.trace_id AS trace_id, u.answer_json AS answer_json
ORDER BY u.n
