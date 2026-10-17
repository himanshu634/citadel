"""One real question against brain_synthetic. Costs a few cents; runs only with a key set.

ANTHROPIC_API_KEY=... make test ARGS="apps/agents/tests/test_agent_live.py"
"""

from __future__ import annotations

import pytest
from agents.ask import ask
from brain import db
from brain.config import get_settings


def _ready() -> str | None:
    if not get_settings().anthropic_api_key:
        return "ANTHROPIC_API_KEY is not set"
    try:
        if not db.graph_exists("synthetic"):
            return "brain_synthetic is not loaded (make synthetic)"
    except Exception:
        return "FalkorDB is not reachable (make up)"
    return None


@pytest.mark.skipif(bool(_ready()), reason=_ready() or "")
def test_live_answer_cites_graph_nodes():
    a = ask("synthetic", "Why did we switch sessions to JWT, and who did it?")
    assert a.text, a.stop
    assert a.sources, "the answer should cite at least one node"
    assert any(s.uid.startswith("synthetic:") for s in a.sources)
    assert a.usage["output_tokens"] > 0
