// purpose: Count nodes per label and relationships per type in one company graph. Used by
//          `brain stats` and as the summary after `brain ingest`.
//          The first half groups nodes by their kind label, the second groups edges by type;
//          UNION ALL stacks both into one table.
// params:  none
// returns: kind ('node' | 'relationship'), type (label or relationship type), count
// example: make stats SLUG=synthetic
MATCH (n)
WITH head([l IN labels(n) WHERE l <> 'Node']) AS label
RETURN 'node' AS kind, label AS type, count(*) AS count
UNION ALL
MATCH ()-[r]->()
RETURN 'relationship' AS kind, type(r) AS type, count(r) AS count
