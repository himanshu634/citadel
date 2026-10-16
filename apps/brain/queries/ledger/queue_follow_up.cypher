// purpose: pm's follow-up queue: claims that need a task and have none yet, oldest first. That is
//          an accepted owner, expert or decision claim (tell the people it concerns), or a claim
//          that conflicts with a source (fix the source).
// params:  none
// returns: claim (its properties; agents.keeper.model.Claim)
// example: store.read("ledger/queue_follow_up", {})
MATCH (c:Claim)
WHERE (c.status = 'accepted' AND c.kind IN ['owner', 'expert', 'decision'])
   OR c.status = 'conflicts_with_source'
OPTIONAL MATCH (f:FollowUp {claim: c.uid})
WITH c, count(f) AS followups
WHERE followups = 0
RETURN properties(c) AS claim
ORDER BY c.updated_at, c.uid
