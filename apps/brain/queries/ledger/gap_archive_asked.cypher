// purpose: Record that the Keeper asked the Archivist about a gap. Once per gap, ever: it matches
//          only while archive_asked is not yet true, so of two racing asks only one wins.
// params:  $uid (Gap.uid)
// returns: uid. No rows: the gap already asked (or there is no such gap).
// example: store.write("ledger/gap_archive_asked", "citadel_keeper", {"uid": "gap:1a2b3c4d5e6f"})
MATCH (g:Gap {uid: $uid})
WHERE coalesce(g.archive_asked, false) = false
SET g.archive_asked = true
RETURN g.uid AS uid
