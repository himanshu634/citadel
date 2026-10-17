"""Offline policies, one per (role, job). `offline_client` plays one through the real loop."""

from __future__ import annotations

from agents.policies import keeper, pm, qa
from agents.policies.base import Policy, Results, ScriptedClient

POLICIES: dict[tuple[str, str], Policy] = {
    ("pm", "consult"): pm.consult,
    ("pm", "follow_up"): pm.follow_up,
    ("qa", "consult"): qa.consult,
    ("keeper", "decide"): keeper.decide,
}


def offline_client(role: str, job: str) -> ScriptedClient:
    return ScriptedClient(POLICIES[(role, job)])


__all__ = ["POLICIES", "Policy", "Results", "ScriptedClient", "offline_client"]
