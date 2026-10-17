// purpose: Write one step of a review for the activity trail: a graph-tool call of a pm, qa or
//          keeper job (written `running` when it starts), or a job's submit (written ended).
//          Written again with the same (review, n), it is overwritten. A step written on a
//          running review is its heartbeat.
// params:  $review (Review uid), $n (1.. within the review), $actor, $tool,
//          $kind ('graph' | 'submit'), $input (JSON text), $status ('running' | 'done' |
//          'failed'), $count, $error (each may be null), $touched: [brain uid], $at (ISO)
// returns: review, n. No rows: no such review.
// notes:   A step not written `running` is ended at $at.
// example: store.write("ledger/write_step", "citadel_keeper", {"review": "review:1a2b3c4d",
//          "n": 1, "actor": "pm", "tool": "work_history", "input": "{\"system\": \"Auth\"}",
//          "at": "2026-10-17T10:00:00Z"})
MATCH (r:Review {uid: $review})
MERGE (r)-[:HAS_STEP]->(s:ReviewStep {review: $review, n: $n})
SET s.actor = $actor,
    s.tool = $tool,
    s.kind = $kind,
    s.input = $input,
    s.status = $status,
    s.count = $count,
    s.error = $error,
    s.touched = $touched,
    s.started_at = $at,
    s.ended_at = CASE WHEN $status = 'running' THEN null ELSE $at END,
    r.heartbeat_at = CASE WHEN r.state = 'running' THEN $at ELSE r.heartbeat_at END
RETURN s.review AS review, s.n AS n
