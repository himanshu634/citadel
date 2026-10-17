// purpose: Flag nodes the Archivist loaded from before the ingest window. Matches by uid among
//          WorkItem and Document (a Linear document is archived too); a uid not in the graph
//          marks nothing. `ref` is the external reference (e.g. "github:acme/w#812") that
//          archive_resolve matches against other items' unresolved_refs.
// params:  $rows: [{uid, ref, archived_at, request}]
// returns: n (nodes marked)
// example: loader.mark_archived("falkordb", [{"uid": "github:a/b:pr:9", "ref": "github:a/b#9",
//          "archived_at": "2026-10-17T00:00:00Z", "request": "why was auth rewritten?"}])
UNWIND $rows AS row
MATCH (a {uid: row.uid})
WHERE a:WorkItem OR a:Document
SET a.archived = true,
    a.archived_at = row.archived_at,
    a.archive_request = row.request,
    a.ref = row.ref
RETURN count(a) AS n
