// purpose: pm's follow-up queue: claims that need a task and have none yet, oldest first. That is
//          an accepted owner, expert or decision claim (tell the people it concerns), or a claim
//          that conflicts with a source (fix the source). A claim pm already tried once without
//          opening a task (`follow_up_tried`) is left out.
// params:  none
// returns: claim (its properties; agents.keeper.model.Claim)
// example: store.read("ledger/queue_follow_up", {})
MATCH (c:Claim)
WHERE ((c.status = 'accepted' AND c.kind IN ['owner', 'expert', 'decision'])
       OR c.status = 'conflicts_with_source')
  AND coalesce(c.follow_up_tries, 0) = 0
OPTIONAL MATCH (f:FollowUp {claim: c.uid})
WITH c, count(f) AS followups
WHERE followups = 0
RETURN properties(c) AS claim
ORDER BY c.updated_at, c.uid
