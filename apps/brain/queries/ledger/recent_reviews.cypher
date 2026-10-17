// purpose: The latest review runs that did something to show, newest first, for the Systems
//          page's activity. Skipped reviews (no API key: re-project and notice only, no steps)
//          are left out, so they never push real ones out of the limit.
// params:  $limit
// returns: review (its properties; agents.keeper.model.Review)
// example: store.read("ledger/recent_reviews", {"limit": 6})
MATCH (r:Review)
WHERE r.state <> 'skipped'
RETURN properties(r) AS review
ORDER BY r.seq DESC
LIMIT $limit
