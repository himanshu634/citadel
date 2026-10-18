"""Agent roles. `ROLES` is the registry; each module defines one `ROLE`.

`brain` answers Ask; the Keeper's review run (`agents/keeper/review.py`) runs the pm and qa
consult jobs, the keeper decide job and pm's follow-up job. The archivist's one job runs through
`agents.archivist.job.answer_request`.
"""

from __future__ import annotations

from agents.roles import archivist, brain, keeper, pm, qa
from agents.roles.base import Ctx, Job, Role, Subject

ROLES: dict[str, Role] = {
    r.name: r for r in (pm.ROLE, qa.ROLE, brain.ROLE, keeper.ROLE, archivist.ROLE)
}

__all__ = ["ROLES", "Ctx", "Job", "Role", "Subject"]
