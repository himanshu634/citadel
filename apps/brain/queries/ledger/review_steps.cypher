// purpose: The steps of some reviews, for the Systems page's activity trail: one read for every
//          review the page shows. Each step carries its review's uid.
// params:  $reviews: [Review uid]
// returns: step (its properties; agents.keeper.model.ReviewStep, `input` as JSON text), by
//          review, then in the order they ran
// example: store.read("ledger/review_steps", {"reviews": ["review:1a2b3c4d"]})
MATCH (s:ReviewStep)
WHERE s.review IN $reviews
RETURN properties(s) AS step
ORDER BY s.review, s.n
