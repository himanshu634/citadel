// purpose: Record one find of a request. One find per (request, item): a repeat updates it. No
//          request with this uid: nothing is written.
// params:  every agents.keeper.model.ArchiveFind field: $request, $uid, $url, $title, $date,
//          $why, $quote, $verdict, $evidence: [uid], $superseded_by (url, date and superseded_by
//          may be null)
// returns: request, uid. No rows: there is no such request.
// example: store.write("ledger/archive_write_find", "citadel_archivist", ArchiveFind(...).model_dump())
MATCH (r:ArchiveRequest {uid: $request})
MERGE (f:ArchiveFind {request: $request, uid: $uid})
SET f.url = $url,
    f.title = $title,
    f.date = $date,
    f.why = $why,
    f.quote = $quote,
    f.verdict = $verdict,
    f.evidence = $evidence,
    f.superseded_by = $superseded_by
RETURN f.request AS request, f.uid AS uid
