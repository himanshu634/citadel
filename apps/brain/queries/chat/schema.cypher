// purpose: Indexes for the chat history in agent_<slug> (beside LangGraph's checkpoints): the
//          chat list reads threads by updated_at, a thread's reads go by thread_id, writes find
//          their node by uid, and "which chats touched X" starts from Ref.uid.
// params:  none
// returns: nothing
// notes:   One statement per line. Applied once per process per company by
//          agents.history; "already indexed" errors are skipped.
// example: GraphChatStore("synthetic").list_threads()
CREATE INDEX FOR (n:Thread) ON (n.id);
CREATE INDEX FOR (n:Thread) ON (n.updated_at);
CREATE INDEX FOR (n:Turn) ON (n.uid);
CREATE INDEX FOR (n:Turn) ON (n.thread_id);
CREATE INDEX FOR (n:LLMCall) ON (n.uid);
CREATE INDEX FOR (n:LLMCall) ON (n.thread_id);
CREATE INDEX FOR (n:ToolCall) ON (n.uid);
CREATE INDEX FOR (n:ToolCall) ON (n.thread_id);
CREATE INDEX FOR (n:Ref) ON (n.uid);
