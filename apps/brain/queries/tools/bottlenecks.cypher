// purpose: Which work items does everything else go through? Betweenness centrality over work
//          items and the links between them (BLOCKS, CLOSES, MENTIONS): a ticket, issue or PR
//          scores high when many dependency chains between other work pass through it.
//          FalkorDB's betweenness is directed and counts shortest paths from a sample of start
//          nodes drawn with replacement (at most 512, at most the node count), so one run can
//          miss a start node on a small graph. The score is the sum of 8 runs with fixed seeds:
//          an estimate (only the ranking means anything) that is the same on every run. Only
//          work items on at least one chain (score > 0) are returned; none
//          means the graph has no such chains. Work items opened by bots are left out. With
//          $open_only only open ones (a ticket is open until its status_category is done or
//          canceled). A graph without work items, or without any of the three links, gives no
//          rows instead of an error.
// params:  $open_only (bool), $limit (int)
// returns: uid, kind, number, key, title, state, url, score (betweenness, higher sits on more
//          chains), highest first
// example: make query TOOL=bottlenecks P="limit=5"
CALL db.labels() YIELD label
WITH collect(label) AS labels
CALL db.relationshipTypes() YIELD relationshipType
WITH labels, collect(relationshipType) AS types
WITH labels, [t IN ['BLOCKS', 'CLOSES', 'MENTIONS'] WHERE t IN types] AS rels
WHERE 'WorkItem' IN labels AND size(rels) > 0
UNWIND range(1, 8) AS seed
WITH {nodeLabels: ['WorkItem'], relationshipTypes: rels, samplingSize: 512, samplingSeed: seed}
     AS config
CALL algo.betweenness(config) YIELD node, score
WITH node, sum(score) AS score
WHERE score > 0
WITH node, score  // a pattern test beside the aggregate in one WHERE is a FalkorDB type error
WHERE NOT (node)<-[:AUTHORED]-(:Person {is_bot: true})
  AND (NOT $open_only
       OR coalesce(NOT node.status_category IN ['done', 'canceled'], node.state = 'open'))
RETURN node.uid AS uid, node.kind AS kind, node.number AS number, node.key AS key,
       node.title AS title, node.state AS state, node.url AS url, score
ORDER BY score DESC, uid
LIMIT $limit
