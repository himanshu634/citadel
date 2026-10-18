"""The named Cypher files themselves: rules every query must keep, checked without a graph."""

from __future__ import annotations

import re

from brain import queries


def test_no_query_takes_a_node_kind_from_its_first_label():
    """Every brain node carries `Node` beside its kind label, and FalkorDB lists labels in the
    order the graph first saw them, so `labels(n)[0]` may be 'Node'. A query that needs the
    kind filters it out: head([l IN labels(n) WHERE l <> 'Node'])."""
    offenders = [
        f"{name}: {line.strip()}"
        for folder in ("tools", "keeper", "graph", "sources", "load")
        for name in queries.list_names(folder)
        for line in queries.get(name).body.splitlines()
        if re.search(r"labels\(\w+\)\[0\]", line)
    ]
    assert offenders == []
