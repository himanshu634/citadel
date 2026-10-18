// purpose: The newest answered request for a question that may be served again (rule 15): same
//          norm, answered, not partial, updated at or after $since. An `ask`-tier request that
//          found nothing is never served to the `keeper` tier (it searched less).
// params:  $norm, $asked_by (ask | keeper: who wants the answer), $since (ISO)
// returns: request (its properties; agents.keeper.model.ArchiveRequest), at most one
// example: store.read("ledger/archive_recall", {"norm": "drop sqlite why", "asked_by": "ask",
//          "since": "2026-09-17T10:00:00Z"})
MATCH (r:ArchiveRequest {norm: $norm, status: 'answered'})
WHERE coalesce(r.partial, false) = false
  AND r.updated_at >= $since
  AND NOT ($asked_by = 'keeper' AND r.asked_by = 'ask' AND r.outcome = 'nothing_found')
RETURN properties(r) AS request
ORDER BY r.updated_at DESC, r.uid DESC
LIMIT 1
