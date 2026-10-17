// purpose: pm's follow-up task for one claim. Idempotent: one per claim, uid followup:<claim>
//          (agents.keeper.model.followup_uid); a second open changes nothing.
// params:  $claim (Claim.uid), $title, $body, $by ('pm'), $now (ISO)
// returns: uid, created (bool)
// example: store.write("ledger/open_followup", "citadel_pm", {"claim": "claim:1a2b3c4d5e6f",
//          "title": "Fix the source: update CODEOWNERS for Billing", "body": "...", "by": "pm",
//          "now": "2026-10-17T11:00:00Z"})
OPTIONAL MATCH (old:FollowUp {uid: 'followup:' + $claim})
WITH old
MERGE (f:FollowUp {uid: 'followup:' + $claim})
ON CREATE SET f.claim = $claim,
              f.title = $title,
              f.body = $body,
              f.by = $by,
              f.status = 'open',
              f.created_at = $now
RETURN f.uid AS uid, old IS NULL AS created
