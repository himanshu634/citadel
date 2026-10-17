// purpose: Record which gaps a review picked, and the first one's text (the run's title on the
//          activity trail; a gap's text never changes).
// params:  $uid (Review uid), $gaps: [gap uid] in pick order, $gap_text (or null)
// returns: uid. No rows: no such review.
// example: store.write("ledger/review_picked", "citadel_keeper", {"uid": "review:1a2b3c4d",
//          "gaps": ["gap:1a2b3c4d5e6f"], "gap_text": "Who owns billing?"})
MATCH (r:Review {uid: $uid})
SET r.gaps = $gaps,
    r.gap_text = $gap_text
RETURN r.uid AS uid
