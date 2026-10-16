// purpose: Replace a work item's assignees: (Person)-[:ASSIGNED_TO]->(WorkItem). Every existing
//          ASSIGNED_TO edge of the item is deleted, then one is merged for each person in the
//          row, so reassigning moves the edge and an empty list unassigns. Rows are sent only
//          for items whose source tracks assignees. People that are not in the graph are skipped.
//          The edge's `source` is the work item's source.
//          One statement (FalkorDB runs one per query): delete, then merge, in the same pass.
// params:  $rows: [{work_item_uid, person_uids, source}]
// returns: n (work items matched; rows for missing items are dropped)
// example: loader.load(...) runs it after authorship
UNWIND $rows AS row
MATCH (w:WorkItem {uid: row.work_item_uid})
OPTIONAL MATCH (:Person)-[old:ASSIGNED_TO]->(w)
DELETE old
WITH DISTINCT w, row
OPTIONAL MATCH (p:Person) WHERE p.uid IN row.person_uids
FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END | MERGE (p)-[r:ASSIGNED_TO]->(w) SET r.source = row.source)
RETURN count(DISTINCT w) AS n
