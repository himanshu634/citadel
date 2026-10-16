// purpose: Full-text (RediSearch) indexes over the text people search for: PR/issue titles and
//          bodies, and document titles and bodies. They back `related_work_items`.
// params:  none
// returns: nothing (indices_created count)
// notes:   Syntax checked against the running engine and the falkordb client
//          (Graph.create_node_fulltext_index emits this same form). Query them with
//          CALL db.idx.fulltext.queryNodes('WorkItem', $text) YIELD node, score
// example: brain schema falkordb
CREATE FULLTEXT INDEX FOR (n:WorkItem) ON (n.title, n.body);
CREATE FULLTEXT INDEX FOR (n:Document) ON (n.title, n.body);
