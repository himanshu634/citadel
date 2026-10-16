// purpose: Append one entry to the Keeper's log. Entries are never changed; `seq` numbers them in
//          the order they were written, so entries with the same `at` still read back in order.
// params:  $uid, $at (ISO), $actor, $action, $why, $gap, $claim (each may be null),
//          $evidence: [uid]
// returns: uid
// example: store.write("ledger/log", "citadel_keeper", {"uid": "log:20261017T100000Z-3fa2c1",
//          "at": "2026-10-17T10:00:00Z", "actor": "keeper", "action": "gap_opened",
//          "why": "Ask found no sources", "gap": "gap:1a2b3c4d5e6f", "claim": null,
//          "evidence": []})
OPTIONAL MATCH (l:LogEntry)
WITH count(l) AS n
CREATE (e:LogEntry {
    uid: $uid,
    seq: n,
    at: $at,
    actor: $actor,
    action: $action,
    why: $why,
    gap: $gap,
    claim: $claim,
    evidence: $evidence
})
RETURN e.uid AS uid
