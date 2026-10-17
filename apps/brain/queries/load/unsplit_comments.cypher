// purpose: The comment chunks written whole, before long text was cut (they have no idx), for
//          loader.backfill_chunks to cut. The chunk holds the whole comment, so it is the
//          comment's only copy: its uid is 'chunk:' + the comment's uid.
// params:  none
// returns: comment_uid, work_item_uid, author_uid, text, created_at, ts, source, url (what
//          loader._write_comment_chunks takes)
// example: loader.backfill_chunks("falkordb")
MATCH (c:Chunk {kind: 'comment'})-[:FROM]->(w:WorkItem)
WHERE c.idx IS NULL
RETURN substring(c.uid, 6) AS comment_uid, w.uid AS work_item_uid, c.author_uid AS author_uid,
       coalesce(c.text, '') AS text, c.created_at AS created_at, c.ts AS ts,
       c.source AS source, c.url AS url
ORDER BY comment_uid
