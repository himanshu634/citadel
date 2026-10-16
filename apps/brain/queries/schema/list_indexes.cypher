// purpose: List the indexes on a company graph, so `brain schema` can show what exists and warn
//          when the vector index dimension does not match EMBEDDING_DIM.
// params:  none
// returns: label, properties, types (per property: RANGE / FULLTEXT / VECTOR), options, status
// example: brain schema falkordb
CALL db.indexes() YIELD label, properties, types, options, status
RETURN label, properties, types, options, status
ORDER BY label
