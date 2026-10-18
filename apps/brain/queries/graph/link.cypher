// purpose: Every relationship between two nodes, either way round, with what each stores, for
//          the Graph page's hover card on a link (the map's own read carries no link properties:
//          a TOUCHES file list on every link would make the whole-graph read much bigger).
// params:  $a, $b (the two node uids)
// returns: source, rel, target, props (the relationship's properties), ordered by rel, source;
//          no rows when the nodes are not linked
// example: graph_view.link_details("synthetic", "person:erin", "synthetic:pr:4")
MATCH (a:Node {uid: $a})-[r]-(b:Node {uid: $b})
RETURN startNode(r).uid AS source, type(r) AS rel, endNode(r).uid AS target,
       properties(r) AS props
ORDER BY rel, source
