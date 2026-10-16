"""Brain agent: answers people's questions with citations (`brain ask` / `brain chat`, in
`agents/ask.py`). It has no queue and writes nothing to the brain; listed here so its user and
tools sit in the same registry as the other roles (docs/agents.md, "8. Brain agent")."""

from __future__ import annotations

from brain.agents.roles.base import Role
from brain.tools import TOOLS

ROLE = Role(
    name="brain",
    db_user="citadel_brain",
    read_tools=tuple(
        sorted(
            {*TOOLS, "decisions_as_of", "decisions_for_system", "release_contents", "task_timeline"}
        )
    ),
    jobs=(),
    summary="Answers people's questions with sources (brain ask / brain chat).",
)
