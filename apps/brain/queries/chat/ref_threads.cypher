// purpose: The chats that touched or cited one node of the company graph, newest first
//          ("what did we already ask about Auth?").
// params:  $uid (a brain_<slug> uid), $limit
// returns: id, title, created_at, updated_at, turns, last_status
// example: GET /api/companies/synthetic/refs/system:Auth/threads
MATCH (r:Ref {uid: $uid})<-[:TOUCHED|CITED]-(x)
WITH DISTINCT x.thread_id AS id
MATCH (t:Thread {id: id})
RETURN t.id AS id, t.title AS title, t.created_at AS created_at, t.updated_at AS updated_at,
       t.turn_count AS turns, t.last_status AS last_status
ORDER BY t.updated_at DESC
LIMIT $limit
