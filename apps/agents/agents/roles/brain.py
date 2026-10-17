"""Brain agent: answers people's questions with citations (`agents ask` / `agents chat`, in
`agents/ask.py`). It has no queue and writes nothing to the brain; listed here so its user and
tools sit in the same registry as the other roles."""

from __future__ import annotations

from brain.tools import TOOLS

from agents.roles.base import Role

ROLE = Role(
    name="brain",
    db_user="citadel_brain",
    read_tools=tuple(sorted(TOOLS)),
    jobs=(),
    summary="Answers people's questions with sources (agents ask / agents chat).",
)
