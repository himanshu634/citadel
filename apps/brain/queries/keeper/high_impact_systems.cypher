// purpose: How widely each system is coupled: the number of distinct other systems changed in the
//          same commits (Change -TOUCHES-> both). keeper.high_impact_systems keeps the top quarter;
//          a claim about one of those needs a lead's approval (the critical rule).
// params:  none
// returns: uid (system uid), partners (distinct co-changing systems), most first. Systems with
//          no partner give no row.
// example: keeper.high_impact_systems("synthetic")
MATCH (s:System)<-[:TOUCHES]-(:Change)-[:TOUCHES]->(other:System)
WHERE other <> s
RETURN s.uid AS uid, count(DISTINCT other) AS partners
ORDER BY partners DESC, uid
