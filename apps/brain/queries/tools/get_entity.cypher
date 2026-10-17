// purpose: Open one node found through another tool: its main fields plus its direct neighbours
//          in both directions (who wrote it, what it touches, closes, mentions, its comment
//          chunks), so an agent can read a PR, issue, document, person or system and follow links.
// params:  $uid, $limit (int, max neighbours)
// returns: uid, label, title, kind, state, url, date, body (first 2000 chars),
//          neighbour_count, neighbours ([{rel, direction 'out'|'in', uid, label, title, url}],
//          ordered by rel then uid, capped at $limit)
// notes:   Chunks of kind work_item and document are left out of the neighbours (and of
//          neighbour_count): their text is already `body`, and a long document's many chunks
//          would sort before its MENTIONS links and push them past $limit. Opening such a chunk
//          by its own uid (a semantic_search chunk_uid) still works.
// example: make query TOOL=get_entity P="uid=synthetic:pr:4"
MATCH (n {uid: $uid})
OPTIONAL MATCH (n)-[r]-(m)
WHERE NOT (m:Chunk AND m.kind IN ['work_item', 'document'])
WITH n, r, m ORDER BY type(r), m.uid
WITH n, collect(CASE WHEN r IS NULL THEN NULL ELSE {
       rel: type(r),
       direction: CASE WHEN startNode(r) = n THEN 'out' ELSE 'in' END,
       uid: m.uid, label: labels(m)[0],
       title: coalesce(m.title, m.subject, m.name, m.login, m.path, left(m.text, 80)),
       url: m.url} END) AS all_neighbours
RETURN n.uid AS uid, labels(n)[0] AS label,
       coalesce(n.title, n.subject, n.name, n.login, n.path) AS title, n.kind AS kind,
       n.state AS state, n.url AS url,
       coalesce(n.created_at, n.merged_at, n.date, n.updated_at) AS date,
       left(coalesce(n.body, n.text, ''), 2000) AS body,
       size(all_neighbours) AS neighbour_count, all_neighbours[0..$limit] AS neighbours
