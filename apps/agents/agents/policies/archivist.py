"""Archivist policy: a reference request looks its refs up and fetches the ones the brain lacks;
a topic request searches every source for its text and fetches the top hits. Each fetched item
becomes a find with verdict `holds`, its quote the start of the fetched text, its evidence the
item the request came from (re-read with get_entity) or else the first related work item."""

from __future__ import annotations

from typing import Any

from agents.policies.base import Call, Results, uniq

TOP_HITS = 2  # search hits a topic request fetches
QUOTE_CHARS = 40  # characters of the fetched text a find quotes


def answer_request(context: dict[str, Any], results: Results) -> list[Call] | dict[str, Any]:
    req, sources = context["request"], context.get("sources") or []
    if not (results.called("archive_lookup") or results.called("archive_search")):
        return _first(req, sources)
    in_brain = [r for r in results.rows("archive_lookup") if r.get("in_brain")]
    if req["kind"] == "reference":
        wanted = [(s["source"], s["id"]) for r in results.rows("archive_lookup")
                  if not r.get("in_brain") for s in r.get("sources") or []]  # fmt: skip
    else:
        hits = [h for h in results.rows("archive_search") if not h.get("in_brain")]
        wanted = [(h["source_key"], h["id"]) for h in hits[:TOP_HITS]]
        in_brain += [h for h in results.rows("archive_search") if h.get("in_brain")]
    if wanted and not results.called("archive_fetch"):
        return [("archive_fetch", {"source": s, "id": i}) for s, i in dict.fromkeys(wanted)]
    fetched = [r for r in results.rows("archive_fetch") if not r.get("in_brain")]
    in_brain += [r for r in results.rows("archive_fetch") if r.get("in_brain")]
    evidence = _evidence(req, results)
    if not fetched or evidence is None:
        if in_brain:
            return _answer(req, "already_in_brain", "It is in the brain already.",
                           cites=uniq([r["uid"] for r in in_brain]))  # fmt: skip
        return _answer(req, "nothing_found", "Found nothing older that answers it.")
    finds = [
        {
            "uid": r["uid"],
            "why": f"Matches the request: {r['title']}",
            "quote": " ".join(r["text"].split())[:QUOTE_CHARS],
            "verdict": "holds",
            "evidence": [evidence],
        }
        for r in fetched
    ]
    titles = "; ".join(f"'{r['title']}'" for r in fetched)
    return _answer(req, "found", f"Found {len(fetched)} older item(s): {titles}.", finds=finds,
                   cites=[evidence])  # fmt: skip


def _first(req: dict[str, Any], sources: list[str]) -> list[Call]:
    """See where the request came from (or what the brain has on its text), and look its refs
    up or search every source."""
    calls: list[Call] = []
    if req.get("from_uid"):
        calls.append(("get_entity", {"uid": req["from_uid"]}))
    else:
        calls.append(("related_work_items", {"text": req["text"]}))
    if req["kind"] == "reference":
        return calls + [("archive_lookup", {"ref": r}) for r in req.get("refs") or []]
    return calls + [("archive_search", {"source": s, "terms": req["text"]}) for s in sources]


def _evidence(req: dict[str, Any], results: Results) -> str | None:
    """The brain uid that connects a find to the brain: the request's item, else a related one."""
    seen = {r["uid"] for r in results.rows("get_entity")}
    if req.get("from_uid") in seen:
        return req["from_uid"]
    related = results.rows("related_work_items")
    return related[0]["uid"] if related else None


def _answer(req: dict[str, Any], outcome: str, summary: str, *, finds: list | None = None,
            cites: list[str] | None = None) -> dict[str, Any]:  # fmt: skip
    return {"request": req["uid"], "outcome": outcome, "summary": summary,
            "finds": finds or [], "cites": cites or []}  # fmt: skip
