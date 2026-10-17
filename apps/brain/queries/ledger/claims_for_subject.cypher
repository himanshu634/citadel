// purpose: The claims of one kind about one subject in the given statuses, most recently updated
//          first: the earlier claim a new one supersedes, or what noticing skips.
// params:  $kind, $subject (brain uid), $statuses: [status]
// returns: claim (its properties; agents.keeper.model.Claim)
// example: store.read("ledger/claims_for_subject", {"kind": "owner",
//          "subject": "system:billing", "statuses": ["accepted"]})
MATCH (c:Claim {subject: $subject, kind: $kind})
WHERE c.status IN $statuses
RETURN properties(c) AS claim
ORDER BY c.updated_at DESC, c.uid DESC
