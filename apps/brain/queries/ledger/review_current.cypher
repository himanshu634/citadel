// purpose: The latest review run (running or not), for the Keeper page and "Review now".
// params:  none
// returns: review (its properties; agents.keeper.model.Review), at most one row
// example: store.read("ledger/review_current", {})
MATCH (r:Review)
RETURN properties(r) AS review
ORDER BY r.seq DESC
LIMIT 1
