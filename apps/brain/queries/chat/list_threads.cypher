// purpose: The chat list: threads, most recently active first, one page at a time.
// params:  $before (epoch ms: only threads updated earlier; the last row's updated_at pages on),
//          $limit
// returns: id, title, created_at, updated_at, turns, last_status
// example: GET /api/companies/synthetic/threads?limit=30
MATCH (t:Thread)
WHERE t.updated_at < $before
RETURN t.id AS id, t.title AS title, t.created_at AS created_at, t.updated_at AS updated_at,
       t.turn_count AS turns, t.last_status AS last_status
ORDER BY t.updated_at DESC
LIMIT $limit
