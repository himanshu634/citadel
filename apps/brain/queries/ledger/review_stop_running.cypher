// purpose: Mark every running review `stopped` (stop 'restart'), as builds are after a server
//          restart: the run that was cut off can never finish.
// params:  $now (ISO)
// returns: uid (one row per review stopped)
// example: store.write("ledger/review_stop_running", "citadel_keeper", {"now": "..."})
MATCH (r:Review {state: 'running'})
SET r.state = 'stopped',
    r.stop = 'restart',
    r.ended_at = $now
RETURN r.uid AS uid
