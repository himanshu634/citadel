// purpose: The Keeper's log, newest first, optionally only the entries of one gap or one claim.
// params:  $limit, $gap (or null: any), $claim (or null: any)
// returns: entry (its properties; agents.keeper.model.LogEntry)
// example: store.read("ledger/read_log", {"limit": 50, "gap": "gap:1a2b3c4d5e6f"})
MATCH (l:LogEntry)
WHERE ($gap IS NULL OR l.gap = $gap)
  AND ($claim IS NULL OR l.claim = $claim)
RETURN properties(l) AS entry
ORDER BY l.seq DESC
LIMIT $limit
