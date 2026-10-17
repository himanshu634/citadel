// purpose: Take a projected claim out of use (superseded or stale) without deleting it:
//          keeper_notes reads only accepted claims with no valid_to.
// params:  $uid, $status (the claim's new status), $valid_to (ISO-8601 UTC)
// returns: uid. No row: no projected claim has this uid.
// example: keeper.retire("synthetic", "claim:ab12", "superseded", "2026-10-17T10:00:00Z")
MATCH (n:Claim {uid: $uid})
SET n.status = $status, n.valid_to = $valid_to
RETURN n.uid AS uid
