// purpose: Delete the BLOCKS edges of one origin that the load just finished did not write, so a
//          dependency removed in the tracker disappears from the graph. Edges of other origins
//          are never touched. Not a row batch: it runs once after all links are written.
// params:  $origin (the adapter key), $keep (uids of the BLOCKS links written by this load; an
//          empty list prunes every edge of the origin)
// returns: n (edges deleted)
// example: loader.load(slug, records, origin="linear:acme")
MATCH ()-[r:BLOCKS {origin: $origin}]->()
WHERE NOT r.uid IN $keep
DELETE r
RETURN count(r) AS n
