// purpose: The newest gap of one noticing kind about one subject, in any status. Noticing skips
//          a subject whose latest gap was settled (resolved, dismissed or needs_person).
// params:  $kind, $subject (brain uid)
// returns: gap (its properties; agents.keeper.model.Gap). No rows: no gap about it yet.
// example: store.read("ledger/latest_gap_for_subject", {"kind": "stale_owner",
//          "subject": "system:billing"})
MATCH (g:Gap {kind: $kind, subject: $subject})
RETURN properties(g) AS gap
ORDER BY g.created_at DESC, g.uid DESC
LIMIT 1
