// purpose: Open an Archivist request, or return the one already in flight for the same question.
//          A request that is open or running with the same norm is returned as it is (rule 16:
//          one search per question at a time); otherwise a new open request is created with $uid.
// params:  $uid (used only for a new request), $kind, $text, $refs: [ref], $from_uid, $asked_by,
//          $gap, $thread (the nullable ones may be null), $norm, $now (ISO)
// returns: uid, created (bool), status
// example: store.write("ledger/archive_open_request", "citadel_brain", {"uid": "archive:1a2b3c4d5e6f",
//          "kind": "topic", "text": "why did we drop sqlite", "refs": [], "asked_by": "ask",
//          "norm": "drop sqlite", "now": "2026-10-17T10:00:00Z"})
OPTIONAL MATCH (r:ArchiveRequest {norm: $norm})
WHERE r.status IN ['open', 'running']
WITH r ORDER BY r.created_at, r.uid LIMIT 1
FOREACH (_ IN CASE WHEN r IS NULL THEN [1] ELSE [] END |
    CREATE (:ArchiveRequest {
        uid: $uid,
        kind: $kind,
        text: $text,
        refs: $refs,
        from_uid: $from_uid,
        asked_by: $asked_by,
        gap: $gap,
        thread: $thread,
        status: 'open',
        norm: $norm,
        partial: false,
        calls: 0,
        created_at: $now,
        updated_at: $now
    }))
WITH r
MATCH (x:ArchiveRequest {uid: coalesce(r.uid, $uid)})
RETURN x.uid AS uid, r IS NULL AS created, x.status AS status
