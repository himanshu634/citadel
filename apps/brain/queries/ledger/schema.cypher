// purpose: Indexes for the Keeper's ledger in keeper_<slug>: every write finds its record by
//          uid; gap and review reads filter on status/state.
// params:  none
// returns: nothing
// notes:   One statement per line. Applied once per process per company by
//          agents.keeper.store.KeeperStore; "already indexed" errors are skipped.
// example: KeeperStore("synthetic").write("ledger/open_gap", "citadel_brain", {...})
CREATE INDEX FOR (n:Gap) ON (n.uid);
CREATE INDEX FOR (n:Gap) ON (n.status);
CREATE INDEX FOR (n:LogEntry) ON (n.uid);
CREATE INDEX FOR (n:Review) ON (n.uid);
CREATE INDEX FOR (n:Review) ON (n.state);
