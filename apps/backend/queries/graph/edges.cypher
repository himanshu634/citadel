// purpose: Every relationship between two drawable nodes (the same labels as graph/nodes), so
//          the Graph page can draw links and count neighbours without a query per node.
// params:  $labels (the node labels to draw)
// returns: source (uid), rel (relationship type), target (uid), ordered by source, rel, target
// example: graph_view.load("synthetic")
MATCH (a)-[r]->(b)
WHERE labels(a)[0] IN $labels AND labels(b)[0] IN $labels
RETURN a.uid AS source, type(r) AS rel, b.uid AS target
ORDER BY source, rel, target
