// purpose: The latest review runs (any state), newest first, for the Systems page's activity.
// params:  $limit
// returns: review (its properties; agents.keeper.model.Review)
// example: store.read("ledger/recent_reviews", {"limit": 6})
MATCH (r:Review)
RETURN properties(r) AS review
ORDER BY r.seq DESC
LIMIT $limit
