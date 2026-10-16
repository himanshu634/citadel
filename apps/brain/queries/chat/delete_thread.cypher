// purpose: Delete a thread's history: its tool calls, Claude responses, turns, the thread, then
//          the Refs no other chat links to. LangGraph's checkpoints are deleted separately
//          (FalkorDBSaver.delete_thread).
// params:  $id
// returns: nothing
// notes:   Several statements, run in order, so no step multiplies the rows of another.
// example: DELETE /api/companies/synthetic/threads/abc123
MATCH (c:ToolCall {thread_id: $id}) DETACH DELETE c;
MATCH (l:LLMCall {thread_id: $id}) DETACH DELETE l;
MATCH (u:Turn {thread_id: $id}) DETACH DELETE u;
MATCH (t:Thread {id: $id}) DETACH DELETE t;
MATCH (r:Ref) WHERE NOT (r)--() DELETE r
