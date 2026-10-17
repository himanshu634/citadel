"""QA agent: for the Keeper it answers consults on gaps (regression risk, test evidence), on the
Keeper's ledger store (docs/agents.md, "The Keeper")."""

from __future__ import annotations

from agents.roles.base import Role
from agents.roles.keeper import consult_job

ROLE = Role(
    name="qa",
    db_user="citadel_qa",
    read_tools=(
        "get_entity",
        "keeper_notes",
        "related_work_items",
        "work_history",
    ),
    jobs=(consult_job("qa"),),
    summary="Answers Keeper consults on regression risk and test evidence.",
)
