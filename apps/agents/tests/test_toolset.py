"""The graph toolset over the real brain tools: ticket rows are citable (needs `make up`), and a
tool that cannot run comes back as an error result."""

from __future__ import annotations

from agents.toolset import Toolset
from brain import tools
from brain.testing import needs_graph


@needs_graph
def test_ticket_rows_are_citable(ticket_graph):
    outcome = Toolset(tools.TOOLS, tools.call).call(ticket_graph, "blocked_on", {"login": "carol"})
    assert not outcome.is_error
    assert outcome.seen["synthetic:ticket:PAY-3"]["title"] == "Usage-based add-ons"
    assert "synthetic:pr:9" in outcome.seen


def test_semantic_search_with_embeddings_off_is_an_error_result(embeddings_off):
    # No graph needed: the question is embedded before any query runs, and there is no embedder.
    toolset = Toolset(tools.TOOLS, tools.call)
    outcome = toolset.call("test_none", "semantic_search", {"text": "invoice"})
    assert outcome.is_error
    assert "Semantic search is off" in outcome.content
