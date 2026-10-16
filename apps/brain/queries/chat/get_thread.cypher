// purpose: One thread's header.
// params:  $id
// returns: id, title, created_at, updated_at, turns, last_status (no row: no such thread)
// example: GET /api/companies/synthetic/threads/abc123
MATCH (t:Thread {id: $id})
RETURN t.id AS id, t.title AS title, t.created_at AS created_at, t.updated_at AS updated_at,
       t.turn_count AS turns, t.last_status AS last_status
