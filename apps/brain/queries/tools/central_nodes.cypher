// purpose: What matters most in the company graph? PageRank over the whole graph (every label,
//          every relationship), kept to one label: a system ranks high when many changes,
//          tickets, docs and owners point at it, a work item or document when much links to
//          it. Work items opened by bots are left out. Person is not a choice: people only have
//          outgoing edges, so PageRank gives every one of them the same score.
// params:  $label ('System' | 'WorkItem' | 'Document'), $limit (int)
// returns: uid, label, name (system name, work item or document title), number, kind (the
//          work item's kind, 'document' or 'system'), state, url, score (PageRank, higher is
//          more central), most central first
// example: make query TOOL=central_nodes P="label=WorkItem limit=5"
CALL algo.pageRank(NULL, NULL) YIELD node, score
WITH node, score
WHERE $label IN labels(node)
  AND NOT (node)<-[:AUTHORED]-(:Person {is_bot: true})
RETURN node.uid AS uid, $label AS label, coalesce(node.name, node.title) AS name,
       node.number AS number,
       CASE $label WHEN 'WorkItem' THEN node.kind ELSE toLower($label) END AS kind,
       node.state AS state, node.url AS url, score
ORDER BY score DESC, uid
LIMIT $limit
