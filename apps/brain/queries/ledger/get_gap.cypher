// purpose: One gap by uid.
// params:  $uid
// returns: gap (its properties; agents.keeper.model.Gap)
// example: store.read("ledger/get_gap", {"uid": "gap:1a2b3c4d5e6f"})
MATCH (g:Gap {uid: $uid})
RETURN properties(g) AS gap
