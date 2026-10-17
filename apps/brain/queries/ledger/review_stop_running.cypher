// purpose: Mark every running review `stopped` (stop 'restart'): its run is gone, as builds
//          are after a server restart. Only the API runs reviews, one process per FalkorDB, so
//          a running review that process is not running can never finish. Run at startup and
//          before each review starts (backend.keeper_runs).
// params:  $now (ISO)
// returns: uid (one row per review stopped)
// example: store.write("ledger/review_stop_running", "citadel_keeper", {"now": "..."})
MATCH (r:Review {state: 'running'})
SET r.state = 'stopped',
    r.stop = 'restart',
    r.ended_at = $now
RETURN r.uid AS uid
