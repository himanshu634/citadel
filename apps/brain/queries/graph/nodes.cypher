// purpose: Every node the Graph page can draw, with what it needs to place, colour and name it.
//          Comment chunks are not drawn as nodes: each work item carries their count instead.
//          Bots are returned with is_bot so the page can hide or show them.
// params:  $labels (the node labels to draw, e.g. ["Person", "WorkItem", ...])
// returns: uid, label, title, kind, state, number, url, is_bot, comments (count of comment Chunks;
//          the body and document Chunks of the same node are not comments), ordered by uid
// example: graph_view.load("synthetic")
MATCH (n)
WHERE labels(n)[0] IN $labels
OPTIONAL MATCH (c:Chunk)-[:FROM]->(n)
WHERE c.kind = 'comment'
RETURN n.uid AS uid, labels(n)[0] AS label,
       coalesce(n.name, n.login, n.title, n.subject, n.path) AS title,
       n.kind AS kind, n.state AS state, n.number AS number, n.url AS url,
       coalesce(n.is_bot, false) AS is_bot, count(c) AS comments
ORDER BY uid
