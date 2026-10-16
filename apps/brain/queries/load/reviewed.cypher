// purpose: (Person)-[:REVIEWED {state}]->(WorkItem). One edge per reviewer and PR; it keeps the
//          latest review (by ts), so COMMENTED followed by APPROVED ends as APPROVED.
// params:  $rows: [{person_uid, work_item_uid, state, submitted_at, ts}]  (sorted by ts)
// returns: n (edges ensured)
// example: loader.load(...) runs it after Person and WorkItem nodes
UNWIND $rows AS row
MATCH (p:Person {uid: row.person_uid})
MATCH (w:WorkItem {uid: row.work_item_uid})
MERGE (p)-[r:REVIEWED]->(w)
SET r.state = CASE WHEN r.ts IS NULL OR row.ts >= r.ts THEN row.state ELSE r.state END,
    r.submitted_at = CASE WHEN r.ts IS NULL OR row.ts >= r.ts THEN row.submitted_at ELSE r.submitted_at END,
    r.ts = CASE WHEN r.ts IS NULL OR row.ts >= r.ts THEN row.ts ELSE r.ts END
RETURN count(r) AS n
