"""The agent graph: one LangGraph StateGraph per run, checkpointed per thread.

    START -> router --"brain"--> brain loop (loop.py: call_claude <-> run_tools) -> END
                    --"build"--> builder -> critic -> END

- router: decides who handles a turn. Today every turn is a question, so it always picks the
  brain loop.
- builder / critic: placeholders for the memory track. The Builder will write Decision nodes
  from what a thread established; the Critic will link them with SUPERSEDES / CONTRADICTS.
  They have no logic yet and the router never sends a turn to them.

Compiled with a checkpointer (`checkpoint.checkpointer(slug)`: graph agent_<slug> on the same
FalkorDB), every step is saved under the run's `thread_id`.
"""

from __future__ import annotations

from typing import Any, Literal

import anthropic
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from agents.loop import AgentState, add_brain_loop
from agents.mcp import Connector
from agents.toolset import Toolset

Route = Literal["brain", "build"]


def router(state: AgentState) -> dict[str, Any]:
    """Pick the handler for this turn. Placeholder: every turn is a question for the brain."""
    return {"route": "brain"}


def builder(state: AgentState) -> dict[str, Any]:
    """Placeholder: will turn a thread's findings into Decision nodes."""
    return {}


def critic(state: AgentState) -> dict[str, Any]:
    """Placeholder: will relate new Decisions to old ones (SUPERSEDES / CONTRADICTS)."""
    return {}


def build_graph(
    client: anthropic.Anthropic,
    toolset: Toolset,
    checkpointer: BaseCheckpointSaver | None = None,
    mcp: Connector | None = None,
):
    g = StateGraph(AgentState)
    brain_entry = add_brain_loop(g, client, toolset, mcp=mcp)
    g.add_node("router", router)
    g.add_node("builder", builder)
    g.add_node("critic", critic)
    g.add_edge(START, "router")
    g.add_conditional_edges(
        "router",
        lambda s: s.get("route") or "brain",
        {"brain": brain_entry, "build": "builder"},
    )
    g.add_edge("builder", "critic")
    g.add_edge("critic", END)
    return g.compile(checkpointer=checkpointer)
