// purpose: Delete the SyncState of one source key. Only the cursor record goes: the nodes that
//          source loaded stay. The backend allows it only for keys no longer in the company YAML.
// params:  $key  e.g. "canonical_jsonl:apps/backend/examples/synthetic_company"
// returns: removed (0 or 1)
// example: backend DELETE /api/companies/synthetic/sources/leftovers?key=...
MATCH (s:SyncState {key: $key})
DELETE s
RETURN count(*) AS removed
