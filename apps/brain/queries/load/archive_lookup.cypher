// purpose: Is an item already in the brain? The Archivist's free check before it fetches, and
//          the backends' way to tell which refs of a fetched item point at loaded items. Matches
//          a WorkItem by uid, by container + number (a GitHub "#812"), by key ("ENG-12") or by
//          url, or a Document by uid or url. Unused params are null and match nothing.
// params:  $uid, $container, $number, $key, $url (any may be null)
// returns: uid, label, kind, title, url, number, key, container, created_at, archived
//          (at most one row per label)
// example: archive.backends.lookup_node("falkordb", {"container": "acme/w", "number": 812})
MATCH (n:WorkItem)
WHERE n.uid = $uid
   OR (n.container = $container AND n.number = $number)
   OR n.key = $key
   OR n.url = $url
RETURN n.uid AS uid, 'WorkItem' AS label, n.kind AS kind, n.title AS title, n.url AS url,
       n.number AS number, n.key AS key, n.container AS container, n.created_at AS created_at,
       coalesce(n.archived, false) AS archived
LIMIT 1
UNION
MATCH (n:Document)
WHERE n.uid = $uid OR n.url = $url
RETURN n.uid AS uid, 'Document' AS label, null AS kind, n.title AS title, n.url AS url,
       null AS number, null AS key, null AS container, null AS created_at,
       coalesce(n.archived, false) AS archived
LIMIT 1
