// purpose: Indexes for the Keeper's ledger in keeper_<slug>: every write finds its record by
//          uid; gap and review reads filter on status/state (noticing gaps on subject), consults on gap, claims on
//          subject, follow-ups on claim and review steps on their review.
// params:  none
// returns: nothing
// notes:   One statement per line. Applied once per process per company by
//          agents.keeper.store.KeeperStore; "already indexed" errors are skipped.
// example: KeeperStore("synthetic").write("ledger/open_gap", "citadel_brain", {...})
CREATE INDEX FOR (n:Gap) ON (n.uid);
CREATE INDEX FOR (n:Gap) ON (n.status);
CREATE INDEX FOR (n:Gap) ON (n.subject);
CREATE INDEX FOR (n:LogEntry) ON (n.uid);
CREATE INDEX FOR (n:Review) ON (n.uid);
CREATE INDEX FOR (n:Review) ON (n.state);
CREATE INDEX FOR (n:Consult) ON (n.uid);
CREATE INDEX FOR (n:Consult) ON (n.gap);
CREATE INDEX FOR (n:Claim) ON (n.uid);
CREATE INDEX FOR (n:Claim) ON (n.subject);
CREATE INDEX FOR (n:FollowUp) ON (n.uid);
CREATE INDEX FOR (n:FollowUp) ON (n.claim);
CREATE INDEX FOR (n:ReviewStep) ON (n.review);
