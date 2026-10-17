"""The interface agent jobs use to read and write their records.

Why: ground rule 1 says the graph is the only channel between agents. Every read and write is a
named query, called exactly like `db.run(slug, name, params)`:

    store.read("ledger/queue_consult", {"role": "qa"})
    store.write("ledger/answer_consult", "citadel_qa", {"consult": "consult:3", ...})

A write returns the rows it changed; no rows means its guard did not match ("someone else got
there first" or "not allowed"). A write the database user may not make raises `acl.Refused`.

The implementations are the Keeper's ledger stores (`agents/keeper/store.py`): `KeeperStore` on
keeper_<slug> and `MemoryKeeperStore` for offline runs and tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

Row = dict[str, Any]


class WorkStore(Protocol):
    slug: str

    def read(
        self, name: str, params: Mapping[str, Any] | None = None, *, db_user: str | None = None
    ) -> list[Row]: ...

    def write(self, name: str, db_user: str, params: Mapping[str, Any]) -> list[Row]: ...
