// purpose: (WorkItem)-[:MENTIONS]->(WorkItem) where the target is named by its url, not by a uid
//          the source knows (a ticket that mentions a GitHub PR). The target is the work item
//          whose `url` equals the row's. Rows whose ends are missing are dropped.
// params:  $rows: [{from_uid, to_url, source}]  (to_url is the Link's to_uid without "url:")
// returns: n (edges ensured)
// example: Link(rel="MENTIONS", from_label="WorkItem", to_label="WorkItem", to_uid="url:https://...")
UNWIND $rows AS row
MATCH (a:WorkItem {uid: row.from_uid})
MATCH (b:WorkItem {url: row.to_url})
MERGE (a)-[r:MENTIONS]->(b)
SET r.source = row.source
RETURN count(r) AS n
