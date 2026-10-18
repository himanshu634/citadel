// purpose: Upsert people. MERGE on uid finds or creates the node; SET then updates it, so
//          re-ingesting is safe. coalesce() keeps a known display name when a later record
//          (e.g. one derived from a commit author) has none; 'derived' never overwrites a real source.
// params:  $company, $rows: [{uid, login, display_name, is_bot, source, url}]
// returns: n (rows written)
// example: loader.load("synthetic", [Person(login="alice")])
UNWIND $rows AS row
MERGE (p:Person {uid: row.uid})
SET p:Node,
    p.company = $company,
    p.login = row.login,
    p.display_name = coalesce(row.display_name, p.display_name),
    p.is_bot = row.is_bot,
    p.url = coalesce(row.url, p.url),
    p.source = CASE WHEN row.source = 'derived' AND p.source IS NOT NULL THEN p.source ELSE row.source END
RETURN count(p) AS n
