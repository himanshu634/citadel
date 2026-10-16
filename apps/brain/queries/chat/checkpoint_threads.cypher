// purpose: The thread ids LangGraph has checkpoints for, with no history yet (the backfill's
//          to-do list). Reads FalkorDBSaver's own Checkpoint nodes.
// params:  none
// returns: thread_id
// example: brain chats-backfill synthetic
MATCH (c:Checkpoint)
WITH DISTINCT c.thread_id AS thread_id
OPTIONAL MATCH (t:Thread {id: thread_id})
WITH thread_id, t
WHERE t IS NULL
RETURN thread_id
ORDER BY thread_id
