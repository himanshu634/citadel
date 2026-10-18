// purpose: Open one node found through another tool: its main fields plus its direct neighbours
//          in both directions (who wrote it, what it touches, closes, mentions, its comment
//          chunks), so an agent can read a PR, issue, document, person or system and follow links.
// params:  $uid, $limit (int, max neighbours)
// returns: uid, label, title, kind, state, url, date, body (first 2000 chars),
//          archived (true for an item loaded from before the window, else null), archived_at,
//          unresolved_refs (refs not yet linked, [] if none), superseded_by (uid or null),
//          neighbour_count, neighbours ([{rel, direction 'out'|'in', uid, label, title, url}],
//          ordered by rel then uid, capped at $limit). A Claim neighbour is listed only while
//          it is current (status 'accepted', no valid_to): a retired Keeper claim is never shown.
// notes:   Chunks of kind work_item and document are left out of the neighbours (and of
//          neighbour_count): their text is already `body`, and a long document's many chunks
//          would sort before its MENTIONS links and push them past $limit. Opening such a chunk
//          by its own uid (a semantic_search chunk_uid) still works. A long comment is listed
//          once, by its first piece (idx 0); its other pieces are left out the same way.
// example: make query TOOL=get_entity P="uid=synthetic:pr:4"
MATCH (n:Node {uid: $uid})
OPTIONAL MATCH (n)-[r]-(m)
WHERE NOT (m:Chunk AND (m.kind IN ['work_item', 'document'] OR coalesce(m.idx, 0) > 0))
  AND (NOT m:Claim OR (m.status = 'accepted' AND m.valid_to IS NULL))
WITH n, r, m ORDER BY type(r), m.uid
WITH n, collect(CASE WHEN r IS NULL THEN NULL ELSE {
       rel: type(r),
       direction: CASE WHEN startNode(r) = n THEN 'out' ELSE 'in' END,
       uid: m.uid,
       label: head([l IN labels(m) WHERE l <> 'Node']),
       title: coalesce(m.title, m.subject, m.name, m.login, m.path, left(m.text, 80)),
       url: m.url} END) AS all_neighbours
RETURN n.uid AS uid,
       head([l IN labels(n) WHERE l <> 'Node']) AS label,
       coalesce(n.title, n.subject, n.name, n.login, n.path) AS title, n.kind AS kind,
       n.state AS state, n.url AS url,
       coalesce(n.created_at, n.merged_at, n.date, n.updated_at) AS date,
       left(coalesce(n.body, n.text, ''), 2000) AS body,
       n.archived AS archived, n.archived_at AS archived_at,
       coalesce(n.unresolved_refs, []) AS unresolved_refs, n.superseded_by AS superseded_by,
       size(all_neighbours) AS neighbour_count, all_neighbours[0..$limit] AS neighbours
