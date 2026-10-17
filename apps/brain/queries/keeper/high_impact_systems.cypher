// purpose: How central each system is: PageRank over the whole graph (every label, every
//          relationship), kept to Systems. A system ranks high when many changes, work items,
//          documents, owners and Keeper claims point at it. keeper.high_impact_systems keeps the
//          top quarter; a claim about one of those needs a lead's approval (the critical rule).
// params:  none
// returns: uid (system uid), score (PageRank), most central first. Every System gives a row.
// example: keeper.high_impact_systems("synthetic")
CALL algo.pageRank(NULL, NULL) YIELD node, score
WITH node, score
WHERE node:System
RETURN node.uid AS uid, score
ORDER BY score DESC, uid
