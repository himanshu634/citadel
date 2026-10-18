// purpose: Give every node that has a uid the `Node` label, so `MATCH (n:Node {uid: $uid})` is
//          one lookup in the Node.uid index whatever kind of node it is (FalkorDB range indexes
//          are per label: a label-less `MATCH (n {uid: $uid})` scans every node). Every load
//          query sets the label as it writes; this backfills a graph loaded before it existed.
// params:  none
// returns: n (nodes labelled; 0 when every node already carries it, so re-running is safe)
// example: brain schema falkordb
MATCH (n)
WHERE n.uid IS NOT NULL AND NOT n:Node
SET n:Node
RETURN count(n) AS n
