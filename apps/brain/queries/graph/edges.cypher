// purpose: Every relationship between two drawable nodes (the same labels as graph/nodes), so
//          the Graph page can draw links and count neighbours without a query per node.
// params:  $labels (the node labels to draw)
// returns: source (uid), rel (relationship type), target (uid), props (the relationship's
//          properties: source, count, pattern, state, ...), ordered by source, rel, target
// example: graph_view.load("synthetic")
MATCH (a)-[r]->(b)
WHERE head([l IN labels(a) WHERE l <> 'Node']) IN $labels
  AND head([l IN labels(b) WHERE l <> 'Node']) IN $labels
RETURN a.uid AS source, type(r) AS rel, b.uid AS target, properties(r) AS props
ORDER BY source, rel, target
