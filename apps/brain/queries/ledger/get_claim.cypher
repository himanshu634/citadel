// purpose: One claim by uid.
// params:  $uid
// returns: claim (its properties; agents.keeper.model.Claim)
// example: store.read("ledger/get_claim", {"uid": "claim:1a2b3c4d5e6f"})
MATCH (c:Claim {uid: $uid})
RETURN properties(c) AS claim
