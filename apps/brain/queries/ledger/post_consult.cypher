// purpose: Ask one role (pm or qa) about one attempt at a gap. Idempotent per (gap, role,
//          attempt, archive): uid consult:<gap>:<role>:<attempt>, plus ":archive" for the round
//          after the gap asked the Archivist (agents.keeper.model.consult_uid); a second post
//          changes nothing. A gap reopened after a rejected claim has attempts + 1, and one the
//          Archivist sent back has archive_asked, so either is asked again.
// params:  $gap (Gap.uid), $role ('pm' | 'qa'), $attempt (the gap's attempts now), $archive
//          (the gap's archive_asked now; the store fills false), $now (ISO)
// returns: uid, created (bool)
// example: store.write("ledger/post_consult", "citadel_keeper", {"gap": "gap:1a2b3c4d5e6f",
//          "role": "pm", "attempt": 0, "archive": false, "now": "2026-10-17T10:00:00Z"})
WITH 'consult:' + $gap + ':' + $role + ':' + toString($attempt)
     + CASE WHEN $archive THEN ':archive' ELSE '' END AS uid
OPTIONAL MATCH (old:Consult {uid: uid})
WITH uid, old
MERGE (c:Consult {uid: uid})
ON CREATE SET c.gap = $gap,
              c.role = $role,
              c.attempt = $attempt,
              c.archive = $archive,
              c.status = 'open',
              c.cites = [],
              c.created_at = $now
RETURN c.uid AS uid, old IS NULL AS created
