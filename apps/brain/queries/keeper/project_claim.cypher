// purpose: Project accepted Keeper claims into the brain, so Ask, get_entity, path_between and the
//          Graph page see them as part of the graph. MERGE on uid: projecting again changes
//          nothing, and after a rebuild it restores the claims. Ingest never writes Claim.
// params:  $claims ([{uid, kind, subject, statement, value, valid_from, author, approved_by,
//          about: [uid], evidence: [uid]}]). keeper.project passes only claims whose subject
//          exists, with about (which always holds the subject) and evidence cut to uids that
//          exist, so both lists are non-empty.
// returns: uid of each projected claim
// notes:   title = statement, so get_entity and the Graph page show it. valid_to is cleared:
//          an accepted claim is current. Edges MATCH both ends, so nothing dangles.
//          Callers project only claims with status accepted, because this clears valid_to.
// example: keeper.project("synthetic", [claim])
UNWIND $claims AS c
MERGE (n:Claim {uid: c.uid})
SET n.kind = c.kind, n.subject = c.subject, n.title = c.statement, n.statement = c.statement,
    n.value = c.value, n.status = 'accepted', n.valid_from = c.valid_from, n.valid_to = null,
    n.author = c.author, n.approved_by = c.approved_by
WITH n, c
UNWIND c.about AS about_uid
MATCH (a {uid: about_uid})
MERGE (n)-[:ABOUT]->(a)
WITH DISTINCT n, c
UNWIND c.evidence AS evidence_uid
MATCH (e {uid: evidence_uid})
MERGE (n)-[:EVIDENCE]->(e)
RETURN DISTINCT n.uid AS uid
