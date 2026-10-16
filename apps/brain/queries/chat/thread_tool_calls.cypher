// purpose: Every tool call in a thread (graph tools, answer checks, MCP and server tools).
// params:  $id
// returns: turn, id, call (seq of the response that asked for it), n, tool, kind, server,
//          input_json, status, error, result, ms, count, rows_json, nodes_json, rels_json
// notes:   Unordered across a turn's calls; the reader orders them by call, then step number.
// example: GET /api/companies/synthetic/threads/abc123
MATCH (c:ToolCall {thread_id: $id})
RETURN c.turn AS turn, c.id AS id, c.call AS call, c.n AS n, c.tool AS tool, c.kind AS kind,
       c.server AS server, c.input_json AS input_json, c.status AS status, c.error AS error,
       c.result AS result, c.ms AS ms, c.count AS count, c.rows_json AS rows_json,
       c.nodes_json AS nodes_json, c.rels_json AS rels_json
