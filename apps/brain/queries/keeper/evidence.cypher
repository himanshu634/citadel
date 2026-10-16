// purpose: Which of these uids are nodes in the brain, and what kind of node each is. The Keeper
//          checks a claim's subject and evidence with it before writing or projecting the claim.
// params:  $uids ([uid])
// returns: uid, label (the node's first label, e.g. WorkItem); uids that are not nodes give no row
// example: keeper.evidence("synthetic", ["synthetic:pr:4", "system:Auth"])
UNWIND $uids AS u
MATCH (n {uid: u})
RETURN DISTINCT n.uid AS uid, labels(n)[0] AS label
