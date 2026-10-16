// purpose: Write a new claim in whatever status the Keeper decided (pending_approval, accepted,
//          rejected, conflicts_with_source). Only creates: a uid already taken changes nothing.
// params:  every agents.keeper.model.Claim field: $uid, $kind, $subject, $statement, $value,
//          $about: [uid], $evidence: [uid], $status, $critical, $critical_reasons: [str],
//          $conflict, $valid_from, $valid_to, $author, $approved_by, $why, $gap, $created_at,
//          $updated_at (the nullable ones may be null)
// returns: uid. No rows: a claim with this uid exists.
// notes:   The guard counts: `WITH old WHERE old IS NULL` does not filter in FalkorDB.
// example: store.write("ledger/write_claim", "citadel_keeper", Claim(...).model_dump())
OPTIONAL MATCH (old:Claim {uid: $uid})
WITH count(old) AS taken
WHERE taken = 0
CREATE (c:Claim {
    uid: $uid,
    kind: $kind,
    subject: $subject,
    statement: $statement,
    value: $value,
    about: $about,
    evidence: $evidence,
    status: $status,
    critical: $critical,
    critical_reasons: $critical_reasons,
    conflict: $conflict,
    valid_from: $valid_from,
    valid_to: $valid_to,
    author: $author,
    approved_by: $approved_by,
    why: $why,
    gap: $gap,
    created_at: $created_at,
    updated_at: $updated_at
})
RETURN c.uid AS uid
