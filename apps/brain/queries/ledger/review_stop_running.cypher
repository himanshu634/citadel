// purpose: Mark every running review whose heartbeat (else its start) is older than
//          $stale_before `stopped` (stop 'restart'), as builds are after a server restart: the
//          run that was cut off can never finish. A review still beating (another process runs
//          it, e.g. `agents keeper review`) is left alone.
// params:  $now (ISO), $stale_before (ISO)
// returns: uid (one row per review stopped)
// notes:   The store fills $stale_before from $now (model.REVIEW_STALE_SECONDS). Timestamps
//          compare as text: every one is written as YYYY-MM-DDTHH:MM:SSZ (`iso`).
// example: store.write("ledger/review_stop_running", "citadel_keeper", {"now": "..."})
MATCH (r:Review {state: 'running'})
WHERE coalesce(r.heartbeat_at, r.started_at) < $stale_before
SET r.state = 'stopped',
    r.stop = 'restart',
    r.ended_at = $now
RETURN r.uid AS uid
