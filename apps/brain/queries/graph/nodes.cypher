// purpose: Every node the Graph page can draw, with what it needs to place, colour and name it.
//          Comment chunks are not drawn as nodes: each work item carries their count instead (a
//          long comment cut into pieces counts once: only piece 0).
//          Bots are returned with is_bot so the page can hide or show them.
// params:  $labels (the node labels to draw, e.g. ["Person", "WorkItem", ...])
// returns: uid, label, title, kind, state, number, url, is_bot, comments (count of comment Chunks;
//          the body and document Chunks of the same node are not comments), ordered by uid
// example: graph_view.load("synthetic")
MATCH (n)
WHERE head([l IN labels(n) WHERE l <> 'Node']) IN $labels
OPTIONAL MATCH (c:Chunk)-[:FROM]->(n)
WHERE c.kind = 'comment' AND coalesce(c.idx, 0) = 0
RETURN n.uid AS uid,
       head([l IN labels(n) WHERE l <> 'Node']) AS label,
       coalesce(n.name, n.login, n.title, n.subject, n.path) AS title,
       n.kind AS kind, n.state AS state, n.number AS number, n.url AS url,
       coalesce(n.is_bot, false) AS is_bot, count(c) AS comments
ORDER BY uid
