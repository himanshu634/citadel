// purpose: Range indexes so every MERGE/MATCH on a node's key is an index lookup, not a scan.
//          Every label is keyed by `uid`; login, number and name are the other lookup keys
//          the tools use (people by login, PRs/issues by number, systems by name, tickets by
//          key, work items by url so links can be resolved by url). `Node` is the label every
//          node carries beside its kind (schema/node_label); its uid index serves the lookups
//          that take any kind of node (get_entity, path_between, the Keeper's evidence).
// params:  none
// returns: nothing (indices_created count)
// notes:   One statement per line, because FalkorDB runs one statement per query.
//          Re-running is safe: `brain schema` skips "already indexed" errors.
//          Node stays last: FalkorDB lists a node's labels in the order the graph first saw
//          them, so this keeps the kind first in `labels(n)` on a fresh graph. Queries never
//          rely on that (they read the kind as head([l IN labels(n) WHERE l <> 'Node'])), but
//          the FalkorDB browser and raw reads look right.
// example: brain schema falkordb
CREATE INDEX FOR (n:Person) ON (n.uid);
CREATE INDEX FOR (n:Person) ON (n.login);
CREATE INDEX FOR (n:Team) ON (n.uid);
CREATE INDEX FOR (n:System) ON (n.uid);
CREATE INDEX FOR (n:System) ON (n.name);
CREATE INDEX FOR (n:Change) ON (n.uid);
CREATE INDEX FOR (n:WorkItem) ON (n.uid);
CREATE INDEX FOR (n:WorkItem) ON (n.number);
CREATE INDEX FOR (n:WorkItem) ON (n.key);
CREATE INDEX FOR (n:WorkItem) ON (n.url);
CREATE INDEX FOR (n:Document) ON (n.uid);
CREATE INDEX FOR (n:Chunk) ON (n.uid);
CREATE INDEX FOR (n:Decision) ON (n.uid);
CREATE INDEX FOR (n:Episode) ON (n.uid);
CREATE INDEX FOR (n:SyncState) ON (n.uid);
CREATE INDEX FOR (n:Claim) ON (n.uid);
CREATE INDEX FOR (n:Node) ON (n.uid);
