// purpose: Everything one drawable node stores, for the Graph page's hover card: its kind and
//          every property, as loaded (the map itself carries only what it needs to draw).
// params:  $uid
// returns: uid, label (the node kind), props (all its properties); no row for an unknown uid
// example: graph_view.node_details("synthetic", "synthetic:pr:4")
MATCH (n:Node {uid: $uid})
RETURN n.uid AS uid, head([l IN labels(n) WHERE l <> 'Node']) AS label, properties(n) AS props
