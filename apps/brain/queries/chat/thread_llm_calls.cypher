// purpose: Every Claude response in a thread, in order within each turn.
// params:  $id
// returns: turn, seq, at, model, stop, text, thinking, ms, input_tokens, output_tokens,
//          cache_read, cache_write
// example: GET /api/companies/synthetic/threads/abc123
MATCH (l:LLMCall {thread_id: $id})
RETURN l.turn AS turn, l.seq AS seq, l.at AS at, l.model AS model, l.stop AS stop,
       l.text AS text, l.thinking AS thinking, l.ms AS ms, l.input_tokens AS input_tokens,
       l.output_tokens AS output_tokens, l.cache_read AS cache_read, l.cache_write AS cache_write
ORDER BY l.turn, l.seq
