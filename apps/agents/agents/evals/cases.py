"""The case file: questions with what a good answer must (and must not) contain.

A uid in an expectation is either a literal (`person:ci-bot`) or a `Gold` reference: the uids a
named tool returns for the same graph, read when the run starts. Gold keeps the expected answer
tied to the data, so regenerating the synthetic company doesn't silently break the cases; the
tools themselves are tested in tests/test_graph.py, so here they count as ground truth.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

CASES_DIR = Path(__file__).parent / "cases"


class Gold(BaseModel):
    """The `field` of the first `top` rows of `tool(**params)`."""

    model_config = ConfigDict(extra="forbid")
    tool: str
    params: dict[str, Any] = Field(default_factory=dict)
    field: str
    top: int = 1


UidRef = str | Gold


class Expect(BaseModel):
    """What one turn's answer is graded on. Citations cover `sources` and `path`; text checks are
    case-insensitive substrings (`text_re` is a regex searched with re.I)."""

    model_config = ConfigDict(extra="forbid")
    answered: bool = True  # submit_answer was accepted
    cite_any: list[UidRef] = Field(default_factory=list)  # at least one of these is cited
    cite_all: list[UidRef] = Field(default_factory=list)
    cite_none: list[UidRef] = Field(default_factory=list)
    tools_any: list[str] = Field(default_factory=list)  # at least one of these tools ran
    tools_all: list[str] = Field(default_factory=list)
    tools_none: list[str] = Field(default_factory=list)
    text_any: list[str] = Field(default_factory=list)
    text_all: list[str] = Field(default_factory=list)
    text_none: list[str] = Field(default_factory=list)
    text_re: str | None = None
    max_steps: int | None = None  # graph tool calls in this turn


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str
    expect: Expect = Field(default_factory=Expect)


class Case(BaseModel):
    """One conversation: a single question, or follow-ups in one thread."""

    model_config = ConfigDict(extra="forbid")
    id: str
    tags: list[str] = Field(default_factory=list)
    why: str = ""  # what the case checks, for whoever reads a failure
    turns: list[Turn]


def load(slug: str, path: Path | None = None) -> list[Case]:
    path = path or CASES_DIR / f"{slug}.yaml"
    raw = yaml.safe_load(path.read_text()) or []
    cases = [Case.model_validate(c) for c in raw]
    ids = [c.id for c in cases]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ValueError(f"{path.name}: duplicate case ids {dupes}")
    return cases


DRAFT = "draft"  # a case made from a thumbs-down (evals/drafts.py) that nobody finished yet
# a case that makes the Archivist load into the brain: it changes the data later runs read, so
# it runs only on its own, after `make archive-clear SLUG=synthetic CONFIRM=1` and a rebuild
ARCHIVE = "archive"
SKIPPED = frozenset({DRAFT, ARCHIVE})


def select(cases: list[Case], only: list[str]) -> list[Case]:
    """Cases whose id or a tag matches one of `only`. With `only` empty: every case but drafts,
    whose expectations are still unwritten (`--case draft` runs them), and archive cases, which
    write to the brain (`--case archive` runs them)."""
    if not only:
        return [c for c in cases if not SKIPPED & set(c.tags)]
    return [c for c in cases if c.id in only or set(c.tags) & set(only)]


Runner = Callable[..., list[Any]]  # (slug, tool, **params) -> rows, like brain.tools.call


class GoldResolver:
    """Turns uid refs into uids, calling each distinct Gold query once per run."""

    def __init__(self, slug: str, run: Runner):
        self.slug = slug
        self.run = run
        self.cache: dict[str, list[str]] = {}

    def uids(self, refs: list[UidRef]) -> list[str]:
        out: list[str] = []
        for ref in refs:
            out.extend([ref] if isinstance(ref, str) else self.gold(ref))
        return out

    def gold(self, ref: Gold) -> list[str]:
        key = ref.model_dump_json()
        if key not in self.cache:
            rows = self.run(self.slug, ref.tool, **ref.params)
            data = [r.model_dump(mode="json", by_alias=True) if isinstance(r, BaseModel) else r
                    for r in rows]  # fmt: skip
            uids = [d.get(ref.field) for d in data[: ref.top]]
            if not uids or not all(isinstance(u, str) and u for u in uids):
                raise ValueError(
                    f"gold {ref.tool}({ref.params}).{ref.field} gave {uids!r} on {self.slug}; "
                    "is the graph loaded?"
                )
            self.cache[key] = uids
        return self.cache[key]

    def resolve(self, expect: Expect) -> dict[str, list[str]]:
        return {
            "cite_any": self.uids(expect.cite_any),
            "cite_all": self.uids(expect.cite_all),
            "cite_none": self.uids(expect.cite_none),
        }
