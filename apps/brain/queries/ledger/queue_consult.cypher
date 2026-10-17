// purpose: One role's queue: its open consults, oldest first.
// params:  $role ('pm' | 'qa')
// returns: consult (its properties; agents.keeper.model.Consult)
// example: store.read("ledger/queue_consult", {"role": "qa"})
MATCH (c:Consult {role: $role, status: 'open'})
RETURN properties(c) AS consult
ORDER BY c.created_at, c.uid
