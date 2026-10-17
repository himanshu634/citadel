"""The agent graph: one LangGraph StateGraph per run, checkpointed per thread.

    START -> brain loop (loop.py: call_claude <-> run_tools) -> END

Every turn is a question for the brain loop. Knowledge is written by the Keeper
(`agents/keeper`), not by this graph.

Compiled with a checkpointer (`checkpoint.checkpointer(slug)`: graph agent_<slug> on the same
FalkorDB), every step is saved under the run's `thread_id`.
"""

from __future__ import annotations

import anthropic
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import START, StateGraph

from agents.loop import AgentState, add_brain_loop
from agents.mcp import Connector
from agents.toolset import Toolset


def build_graph(
    client: anthropic.Anthropic,
    toolset: Toolset,
    checkpointer: BaseCheckpointSaver | None = None,
    mcp: Connector | None = None,
):
    g = StateGraph(AgentState)
    g.add_edge(START, add_brain_loop(g, client, toolset, mcp=mcp))
    return g.compile(checkpointer=checkpointer)
