// purpose: Why are these two things connected? The shortest paths between two nodes (any
//          labels, by uid), following relationships in either direction. Uses FalkorDB's
//          algo.SPpaths procedure with relDirection 'both', because the built-in shortestPath()
//          only supports directed traversals. Text chunks (FROM) are left out of the walk.
// params:  $from_uid, $to_uid, $max_len (int, hops), $paths (int, how many paths)
// returns: length, nodes ([{label, uid, name, url}]), rels ([{type, from, to}]); no row when
//          the two are not connected within $max_len hops
// example: make query TOOL=path_between P="from_uid=person:erin to_uid=system:Auth"
MATCH (a:Node {uid: $from_uid}), (b:Node {uid: $to_uid})
CALL algo.SPpaths({
  sourceNode: a, targetNode: b, relDirection: 'both', maxLen: $max_len, pathCount: $paths,
  relTypes: ['AUTHORED', 'REVIEWED', 'COMMENTED_ON', 'MEMBER_OF', 'OWNS', 'TOUCHES', 'PART_OF',
             'CLOSES', 'MENTIONS', 'MADE_IN', 'AFFECTS', 'SUPERSEDES', 'CONTRADICTS']
}) YIELD path
RETURN length(path) AS length,
       [n IN nodes(path) | {label: head([l IN labels(n) WHERE l <> 'Node']),
                            uid: n.uid,
                            name: coalesce(n.login, n.name, n.title, n.subject, n.path),
                            url: n.url}] AS nodes,
       [r IN relationships(path) | {type: type(r), from: startNode(r).uid, to: endNode(r).uid}]
         AS rels
ORDER BY length
