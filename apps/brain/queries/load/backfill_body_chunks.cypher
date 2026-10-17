// purpose: Give every WorkItem that has no body chunk one, as work_item_chunk writes it. A graph
//          built before work items had body chunks never gets them from an incremental ingest,
//          because the sync cursor skips the old items. Runs before the embed stage.
// params:  $company
// returns: n (chunks written; 0 when every work item has its body chunk)
// notes:   The text matches loader._titled: the title, then a blank line and the body when the
//          body has more than whitespace (spaces, tabs, line breaks; trim() strips only spaces).
//          Cypher cannot hash, so text_hash stays null and the embed stage fills it from the
//          text; a later load writes the same text and hash, so nothing is embedded twice.
// example: loader.backfill_body_chunks("falkordb")
MATCH (w:WorkItem)
OPTIONAL MATCH (old:Chunk {uid: 'chunk:' + w.uid + ':body'})
WITH w, old
WHERE old IS NULL
WITH w, coalesce(w.body, '') AS body
MERGE (c:Chunk {uid: 'chunk:' + w.uid + ':body'})
SET c.company = $company,
    c.kind = 'work_item',
    c.text = CASE
      WHEN trim(replace(replace(replace(body, '\r', ''), '\n', ''), '\t', '')) = '' THEN w.title
      ELSE w.title + '\n\n' + body END,
    c.created_at = w.created_at,
    c.ts = w.created_ts,
    c.source = w.source,
    c.url = w.url
MERGE (c)-[:FROM]->(w)
RETURN count(c) AS n
