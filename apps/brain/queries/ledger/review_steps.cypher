// purpose: The steps of one review, in the order they ran, for the Systems page's activity trail.
// params:  $review (Review uid)
// returns: step (its properties; agents.keeper.model.ReviewStep, `input` as JSON text)
// example: store.read("ledger/review_steps", {"review": "review:1a2b3c4d"})
MATCH (s:ReviewStep {review: $review})
RETURN properties(s) AS step
ORDER BY s.n
