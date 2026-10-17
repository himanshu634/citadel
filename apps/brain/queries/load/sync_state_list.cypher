// purpose: Every SyncState of a company graph: one per source key ever loaded, including keys
//          that are no longer in the company YAML (the Sources page lists those as leftovers).
// params:  none (the graph is selected by the company slug)
// returns: key, adapter, cursor, window_since, last_run, records (loaded in the LAST run only)
// example: backend GET /api/companies/falkordb/sources
MATCH (s:SyncState)
RETURN s.key AS key, s.adapter AS adapter, s.cursor AS cursor, s.window_since AS window_since,
       s.last_run AS last_run, s.records AS records
ORDER BY key
