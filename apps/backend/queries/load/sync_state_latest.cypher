// purpose: When a company graph was last ingested and from how many sources, for the company
//          list and status. Empty graph (no SyncState nodes) gives null and 0.
// params:  none (the graph is selected by the company slug)
// returns: last_synced_at (latest SyncState.last_run, ISO timestamp or null), sources (count)
// example: api.companies.status_of("falkordb") reads it
MATCH (s:SyncState)
RETURN max(s.last_run) AS last_synced_at, count(s) AS sources
