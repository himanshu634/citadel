// purpose: Record one Claude response of a turn (its text, thinking, tokens, timing) and a
//          ToolCall for every tool it asked for. Graph and submit calls start as 'running' and
//          get their result from tool_done; MCP and server calls arrive finished.
// params:  $turn (Turn.uid), $thread_id, $seq, $at, $model, $stop, $text, $thinking, $ms,
//          $input_tokens, $output_tokens, $cache_read, $cache_write,
//          $calls: [{uid, id, tool, kind, server, input_json, status, error, result}]
// returns: n (tool calls written)
// example: history.Recorder(...).on({"kind": "llm", "seq": 1, ...})
MATCH (u:Turn {uid: $turn})
CREATE (u)-[:HAS_CALL {seq: $seq}]->(l:LLMCall {
    uid: $turn + ':' + toString($seq),
    thread_id: $thread_id,
    turn: $turn,
    seq: $seq,
    at: $at,
    model: $model,
    stop: $stop,
    text: $text,
    thinking: $thinking,
    ms: $ms,
    input_tokens: $input_tokens,
    output_tokens: $output_tokens,
    cache_read: $cache_read,
    cache_write: $cache_write
})
WITH l
UNWIND $calls AS call
MERGE (c:ToolCall {uid: call.uid})
SET c.id = call.id,
    c.thread_id = $thread_id,
    c.turn = $turn,
    c.call = $seq,
    c.tool = call.tool,
    c.kind = call.kind,
    c.server = call.server,
    c.input_json = call.input_json,
    c.status = call.status,
    c.error = call.error,
    c.result = call.result
MERGE (l)-[:REQUESTED]->(c)
RETURN count(c) AS n
