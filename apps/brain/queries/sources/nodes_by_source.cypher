// purpose: How many nodes each `source` label put in the graph, by node label; work items also by
//          kind and state. `source` is the adapter type a record came from (or whatever label a
//          JSONL record carries, like slack_export); `derived` marks people, teams and systems
//          made from links. Nodes without a source (SyncState) are left out.
// params:  none (the graph is selected by the company slug)
// returns: source, label, kind (work items only, else null), state (work items only), n
// example: backend GET /api/companies/falkordb/sources
MATCH (n)
WHERE n.source IS NOT NULL
WITH n.source AS source, head([l IN labels(n) WHERE l <> 'Node']) AS label,
     CASE WHEN n:WorkItem THEN n.kind ELSE null END AS kind,
     CASE WHEN n:WorkItem THEN n.state ELSE null END AS state
RETURN source, label, kind, state, count(*) AS n
ORDER BY source, label, kind, state
