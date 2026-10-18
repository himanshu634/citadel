"""The Archivist's fixed rules. No model decides these (spec: "The Archivist").

Why: what the Archivist says it found must be provable. The run fetches an item from its
source; a find is accepted only if the item was fetched in this run (rule 12), its `quote` is
really in the fetched text or the request named the item exactly (rule 13), and the brain
nodes it cites as evidence exist (rule 3b). `norm` keys the request dedupe (rule 16) and
`recall` serves a question that was answered lately (rule 15). `check_scope` refuses a
reference request none of whose refs a source of the company owns.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

from brain.config import get_settings

from agents.keeper.model import ArchiveRequest, iso

if TYPE_CHECKING:
    from brain.archive.backends import Backend, Fetched

# Words that do not tell two topic questions apart.
STOP_WORDS = frozenset(
    "a an and are as at be by did do does for from how i in is it of on or our that the this "
    "to was we were what when where which who whom why with you".split()
)


class FindLike(Protocol):
    """What `check_find` reads of a find (`ArchiveFind`, or the submit tool's input)."""

    uid: str
    why: str
    quote: str
    verdict: str
    evidence: list[str]
    superseded_by: str | None


def norm(kind: str, text: str, refs: list[str]) -> str:
    """The dedupe key of a request, never empty for a non-empty text: its exact refs (trimmed,
    lowercased, sorted, joined with a comma) when it is a reference request with any, else the
    lowercased words of the text without stop words, each once, sorted. A text of only stop
    words or punctuation ("why?") keys by its lowercased, whitespace-squashed self."""
    if kind == "reference" and refs:
        return ",".join(sorted({r.strip().lower() for r in refs if r.strip()}))
    words = {w for w in re.findall(r"#?\w+", text.lower()) if w not in STOP_WORDS}
    return " ".join(sorted(words)) or " ".join(text.lower().split())


def resolver(backends: Mapping[str, Backend]) -> Callable[[str], set[str]]:
    """`resolve` for `check_find`: every id a request ref stands for: the ref as written, and
    what each backend's `parse_ref` makes of it (no network)."""

    def resolve(ref: str) -> set[str]:
        ids = {ref}
        for b in backends.values():
            if item := b.parse_ref(ref):
                ids.add(item)
        return ids

    return resolve


def split_scope(refs: list[str], backends: Mapping[str, Backend]) -> tuple[list[str], list[str]]:
    """The refs some source of the company claims, and the ones none does, each in order."""
    claimed, dropped = [], []
    for ref in refs:
        owned = any(b.parse_ref(ref) for b in backends.values())
        (claimed if owned else dropped).append(ref)
    return claimed, dropped


def check_scope(refs: list[str], backends: Mapping[str, Backend]) -> str | None:
    """`out_of_scope` when the request has refs and no source of the company claims any of
    them, else None. Unclaimed refs beside a claimed one ("#900 auth") are dropped from the run
    (`split_scope`), not refused.

    A source that would refuse (a private repo without `own` data) is not checked here: the
    backends only say so on use, by raising PermissionError, which the caller turns into a
    `refused: <reason>` request."""
    claimed, dropped = split_scope(refs, backends)
    return "out_of_scope" if dropped and not claimed else None


def _squash(text: str) -> str:
    return " ".join(text.split())


def check_find(
    find: FindLike,
    fetched: Fetched | None,
    request: ArchiveRequest,
    lookup: Callable[[str], dict[str, Any] | None],
    *,
    ids: Iterable[str] = (),
    resolve: Callable[[str], set[str]] | None = None,
) -> str | None:
    """Why this find is refused, or None when it passes. The reason is a sentence the model
    gets back as an error. `fetched` is the item this run fetched under the find's uid; `ids`
    are every id it was fetched under (`ArchiveSession.ids_for`) and `resolve` maps a request
    ref to the ids it stands for (`resolver`): when one of them is the item's, the request named
    the item exactly and no quote is needed."""
    if fetched is None or fetched.candidate.uid != find.uid:  # rule 12
        return f"{find.uid} was not fetched in this run; fetch it before reporting it."
    if not find.why.strip():  # rule 13
        return "why is empty; say why this item answers the request."
    c = fetched.candidate
    names = {n.strip().lower() for n in (*ids, c.uid, c.ref, c.id, c.url) if n}
    resolve = resolve or (lambda ref: {ref})
    named = {i.strip().lower() for r in request.refs for i in resolve(r.strip())}
    if not (request.kind == "reference" and names & named):
        minimum = get_settings().archivist_quote_min
        quote = _squash(find.quote)
        if len(quote) < minimum:
            return f"quote is too short: give at least {minimum} characters of the item's text."
        if quote not in _squash(fetched.text):
            return "quote is not in the fetched text; copy a passage from the item as fetched."
    if not find.evidence:  # rule 3b
        return "evidence is empty; cite the brain uids that back the verdict."
    for uid in find.evidence:
        if lookup(uid) is None:
            return f"evidence {uid} is not in the brain; cite only uids the brain holds."
    if find.verdict == "superseded":
        if not find.superseded_by:
            return "superseded_by is empty; a superseded item needs the uid that replaces it."
        if lookup(find.superseded_by) is None:
            return f"superseded_by {find.superseded_by} is not in the brain."
    elif find.superseded_by:
        return f"superseded_by is only for the verdict superseded, not {find.verdict}."
    return None


def recall(
    store: Any,
    norm_: str,
    asked_by: str,
    now: datetime | str | float,
    *,
    lookup: Callable[[str], dict[str, Any] | None],
) -> ArchiveRequest | None:
    """Rule 15: the newest answered request for this question that may be served again, within
    `archivist_memory_days`, not `partial`; an `ask`-tier `nothing_found` does not serve the
    `keeper` tier, which searches more. An answer whose finds are not all in the brain any more
    (`lookup`, e.g. after `make archive-clear` and a rebuild) is not served: the run happens
    again."""
    if isinstance(now, datetime):
        at = now.astimezone(UTC)
    else:
        at = datetime.fromisoformat(iso(now).replace("Z", "+00:00"))
    since = iso((at - timedelta(days=get_settings().archivist_memory_days)).timestamp())
    rows = store.read(
        "ledger/archive_recall", {"norm": norm_, "asked_by": asked_by, "since": since}
    )
    if not rows:
        return None
    earlier = ArchiveRequest(**rows[0])
    finds = store.read("ledger/archive_finds", {"requests": [earlier.uid]})
    if any(lookup(f["uid"]) is None for f in finds):
        return None
    return earlier
