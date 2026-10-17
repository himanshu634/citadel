// purpose: Record that pm's follow-up job ran on a claim and opened no task (no answer, nothing
//          it could cite), so `queue_follow_up` leaves the claim out: the job is not paid for
//          again on every review. Guarded: only a claim with no try yet, so it counts once.
//          The claim's status and updated_at do not change.
// params:  $claim (Claim.uid), $now (ISO; unused, every ledger write passes it)
// returns: uid, follow_up_tries. No rows: no such claim, or it was tried already.
// example: store.write("ledger/follow_up_tried", "citadel_keeper", {"claim": "claim:1a2b3c4d5e6f",
//          "now": "2026-10-17T11:00:00Z"})
MATCH (c:Claim {uid: $claim})
WHERE coalesce(c.follow_up_tries, 0) = 0
SET c.follow_up_tries = 1
RETURN c.uid AS uid, c.follow_up_tries AS follow_up_tries
