// purpose: Count nodes per label and relationships per type in one company graph. Used by
//          `brain stats` and as the summary after `brain ingest`.
//          The first half groups nodes by their (single) label, the second groups edges by type;
//          UNION ALL stacks both into one table.
// params:  none
// returns: kind ('node' | 'relationship'), type (label or relationship type), count
// example: make stats SLUG=synthetic
MATCH (n)
RETURN 'node' AS kind, labels(n)[0] AS type, count(n) AS count
UNION ALL
MATCH ()-[r]->()
RETURN 'relationship' AS kind, type(r) AS type, count(r) AS count
