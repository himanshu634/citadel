// purpose: The reviews that picked one gap, newest first: where the review page finds the steps
//          the pm, qa and keeper jobs took on the way to a claim (agents.keeper.trail).
// params:  $gap (Gap.uid)
// returns: review (its properties; agents.keeper.model.Review)
// example: store.read("ledger/reviews_for_gap", {"gap": "gap:1a2b3c4d5e6f"})
MATCH (r:Review)
WHERE $gap IN r.gaps
RETURN properties(r) AS review
ORDER BY r.seq DESC
