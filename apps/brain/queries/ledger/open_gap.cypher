// purpose: Open a gap, or bump the live one it repeats. A gap that is open or in_review with the
//          same kind and the same norm (for noticing kinds: the same subject) gets count + 1, the
//          new trace id and any new `about` uids, and keeps its uid. Otherwise a new open gap is
//          created with $uid. A resolved, dismissed or needs_person gap is never bumped.
// params:  $uid (used only for a new gap), $kind, $text, $norm, $subject, $about: [uid],
//          $trace_id (or null), $now (ISO)
// returns: uid, created (bool), count
// notes:   The noticing kinds are agents.keeper.model.NOTICING_KINDS.
// example: store.write("ledger/open_gap", "citadel_brain", {"uid": "gap:1a2b3c4d5e6f",
//          "kind": "failed_question", "text": "Who owns Billing?", "norm": "who owns billing",
//          "subject": null, "about": [], "trace_id": "t1", "now": "2026-10-17T10:00:00Z"})
OPTIONAL MATCH (g:Gap {kind: $kind})
WHERE g.status IN ['open', 'in_review']
  AND CASE WHEN $kind IN ['stale_owner', 'unowned_hot_system']
           THEN g.subject = $subject
           ELSE g.norm = $norm END
WITH g ORDER BY g.created_at, g.uid LIMIT 1
FOREACH (_ IN CASE WHEN g IS NULL THEN [1] ELSE [] END |
    CREATE (:Gap {
        uid: $uid,
        kind: $kind,
        text: $text,
        norm: $norm,
        subject: $subject,
        status: 'open',
        count: 1,
        attempts: 0,
        created_at: $now,
        updated_at: $now,
        trace_ids: CASE WHEN $trace_id IS NULL THEN [] ELSE [$trace_id] END,
        about: $about
    }))
FOREACH (_ IN CASE WHEN g IS NULL THEN [] ELSE [1] END |
    SET g.count = g.count + 1,
        g.updated_at = $now,
        g.trace_ids = g.trace_ids +
            CASE WHEN $trace_id IS NULL OR $trace_id IN g.trace_ids THEN [] ELSE [$trace_id] END,
        g.about = g.about + [a IN $about WHERE NOT a IN g.about])
WITH g
MATCH (r:Gap {uid: coalesce(g.uid, $uid)})
RETURN r.uid AS uid, g IS NULL AS created, r.count AS count
