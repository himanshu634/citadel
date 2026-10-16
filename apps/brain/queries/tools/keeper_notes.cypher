// purpose: What the Keeper holds true about a node beyond the sources: accepted, current claims
//          ABOUT it, each with the evidence it rests on. Ask uses these only for what the sources
//          don't say, and says that part comes from the Keeper.
// params:  $uid (any node's uid, e.g. 'system:Auth')
// returns: uid, kind, statement, value, valid_from, approved_by,
//          evidence ([{uid, label, title, url}]); newest first
// example: make query TOOL=keeper_notes P="uid=system:Auth"
MATCH (c:Claim)-[:ABOUT]->({uid: $uid})
WHERE c.status = 'accepted' AND c.valid_to IS NULL
OPTIONAL MATCH (c)-[:EVIDENCE]->(e)
WITH c, e ORDER BY e.uid
WITH c, collect(CASE WHEN e IS NULL THEN NULL ELSE {
       uid: e.uid, label: labels(e)[0],
       title: coalesce(e.title, e.subject, e.name, e.login, e.path, left(e.text, 80)),
       url: e.url} END) AS evidence
RETURN c.uid AS uid, c.kind AS kind, c.statement AS statement, c.value AS value,
       c.valid_from AS valid_from, c.approved_by AS approved_by, evidence
ORDER BY valid_from DESC, uid
