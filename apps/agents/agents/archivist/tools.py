"""The Archivist's three source tools, beside its graph read tools.

Why: the model chooses only what to look up, search and fetch (a ref, terms, an id); every
external call goes through one `ArchiveSession`, which holds the budgets. These tools adapt it
to the brain loop's toolset:

    archive_lookup(ref)          is it in the brain? free; else which source owns it, as what id
    archive_search(source, terms) candidates older than the window (one call of the budget)
    archive_fetch(source, id)    the item's text (cut to FETCH_CHARS) and its refs (one call);
                                 an item already in the brain is not fetched again (rule 4)

Rows carry `uid`, so the loop's `seen` holds every searched and fetched item and the submit may
name them. A spent budget is an ordinary tool error naming it (rule 11), so the run can still
submit. What the job must act on after the run is noted in `Trouble`: a source that refused
(PermissionError), one that kept failing (`SourceFailed`), the budgets that ran out, and
whether the soft deadline cut the run short.

The soft deadline (rule 8): once `wrap_up()` is true every archive tool refuses with
`WRAP_UP`, so the model submits what it has fetched; its finds are still checked and loaded.
The hard stop is the job's `should_stop` (nothing is applied).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from brain.archive.backends import Candidate, SourceFailed
from brain.archive.session import ArchiveSession, BudgetSpent
from pydantic import BaseModel, ConfigDict, Field

from agents.toolset import Toolset

FETCH_CHARS = 6000  # characters of a fetched item's text the model reads
WRAP_UP = "Time is nearly up: call submit_archive_answer now with what you have fetched."


class TimeUp(Exception):
    """The soft deadline passed: the archive tools refuse, the model should submit."""


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LookupParams(_Params):
    ref: str = Field(
        description="A reference as written: a uid, a URL, '#812', a Linear key ('ENG-12')."
    )


class SearchParams(_Params):
    source: str = Field(description="A source key from the context's sources.")
    terms: str = Field(description="A few plain words to search titles and bodies for.")


class FetchParams(_Params):
    source: str = Field(description="A source key from the context's sources.")
    id: str = Field(description="The item: a search hit's id, or a ref the source owns.")


@dataclass(frozen=True)
class _Tool:
    name: str
    description: str
    params: type[BaseModel]


TOOLS: dict[str, _Tool] = {
    "archive_lookup": _Tool(
        "archive_lookup",
        "Check whether a referenced item is already in the brain (free, no budget). When it is "
        "not, says which source owns the ref and the id to fetch it with.",
        LookupParams,
    ),
    "archive_search": _Tool(
        "archive_search",
        "Search one source for items older than the ingest window. Uses one call of the "
        "request's budget. Hits marked in_brain are loaded already.",
        SearchParams,
    ),
    "archive_fetch": _Tool(
        "archive_fetch",
        "Fetch one older item: its text (title, body, comments) and the refs it points at. "
        "Uses one call of the budget; an item already in the brain is not fetched again.",
        FetchParams,
    ),
}


@dataclass
class Trouble:
    """What went wrong at the sources during a run, for the job to act on afterwards."""

    refused: str | None = None  # a source refused (PermissionError): the request is refused
    failed: str | None = None  # a source kept failing: the request fails (rule 20)
    spent: set[str] = field(default_factory=set)  # budgets that ran out: the answer is partial
    wrapped_up: bool = False  # the soft deadline refused a call: the answer is partial

    @property
    def partial(self) -> bool:
        """The run was cut short by a budget or the deadline (never served from memory)."""
        return bool(self.spent) or self.wrapped_up

    @property
    def halt(self) -> bool:
        """The run should end at its next step."""
        return bool(self.refused or self.failed)


def _candidate(c: Candidate, in_brain: bool) -> dict[str, Any]:
    return {**c.model_dump(mode="json"), "in_brain": in_brain}


@dataclass
class ArchiveTools:
    session: ArchiveSession
    trouble: Trouble = field(default_factory=Trouble)
    wrap_up: Callable[[], bool] | None = None

    def lookup(self, ref: str) -> list[dict[str, Any]]:
        if node := self.session.lookup(ref):
            return [{**node, "in_brain": True}]
        sources = [
            {"source": key, "id": item}
            for key, b in sorted(self.session.backends.items())
            if (item := b.parse_ref(ref))
        ]
        return [{"ref": ref, "in_brain": False, "sources": sources}]

    def search(self, source: str, terms: str) -> list[dict[str, Any]]:
        hits = self.session.search(source, terms)
        return [_candidate(c, self.session.lookup(c.uid) is not None) for c in hits]

    def fetch(self, source: str, id: str) -> list[dict[str, Any]]:
        if node := self.session.lookup(id):
            note = "Already in the brain: read it with get_entity; it is not fetched again."
            return [{**node, "in_brain": True, "note": note}]
        got = self.session.fetch(source, id)
        row = _candidate(got.candidate, False)
        row.pop("snippet", None)
        return [{**row, "text": got.text[:FETCH_CHARS], "refs": list(got.refs)}]

    def run(self, name: str, **params: Any) -> list[dict[str, Any]]:
        handler: Callable[..., list[dict[str, Any]]] = getattr(self, name.removeprefix("archive_"))
        if self.wrap_up is not None and self.wrap_up():
            self.trouble.wrapped_up = True
            raise TimeUp(WRAP_UP)
        try:
            return handler(**params)
        except BudgetSpent as e:
            self.trouble.spent.add(e.budget)
            raise
        except PermissionError as e:
            self.trouble.refused = self.trouble.refused or str(e)
            raise
        except SourceFailed as e:
            self.trouble.failed = self.trouble.failed or str(e)
            raise


def archive_toolset(
    session: ArchiveSession,
    graph: Toolset,
    *,
    trouble: Trouble | None = None,
    wrap_up: Callable[[], bool] | None = None,
) -> Toolset:
    """`graph` (the role's read tools) plus the three archive tools on `session`; what goes
    wrong at the sources is noted in `trouble`; past `wrap_up()` the archive tools refuse."""
    archive = ArchiveTools(session, trouble if trouble is not None else Trouble(), wrap_up)

    def run(slug: str, name: str, **params: Any) -> list[Any]:
        if name in TOOLS:
            return archive.run(name, **params)
        return graph.run(slug, name, **params)

    return Toolset(tools={**graph.tools, **TOOLS}, run=run)
