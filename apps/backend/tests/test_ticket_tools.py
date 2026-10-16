"""The ticket tools against the synthetic company's ten tickets (known answers, spec section 7)."""

from __future__ import annotations

import json
from pathlib import Path

from brain import canonical as c
from brain.adapters.canonical_jsonl import CanonicalJsonlAdapter
from conftest import SYNTHETIC, synthetic_company

TICKETS = SYNTHETIC / "tickets"


def test_synthetic_tickets_validate():
    """The tickets folder reads through the canonical_jsonl adapter: 10 tickets, 4 BLOCKS and 4
    MENTIONS links, and every MENTIONS target is a PR or issue of the base synthetic data."""
    cfg = synthetic_company("x", folder=TICKETS)
    records = list(CanonicalJsonlAdapter().records(cfg, cfg.sources[0], Path("/nonexistent")))
    tickets = [r for r in records if isinstance(r, c.WorkItem)]
    links = [r for r in records if isinstance(r, c.Link)]
    assert len(tickets) == 10
    assert all(t.kind == "ticket" and t.assignees and t.key for t in tickets)
    assert sum(link.rel == "BLOCKS" for link in links) == 4
    mentions = [link for link in links if link.rel == "MENTIONS"]
    assert len(mentions) == 4
    base = {json.loads(line)["uid"] for line in (SYNTHETIC / "work_items.jsonl").open()}
    assert {link.to_uid for link in mentions} <= base
    assert json.loads((TICKETS / "linear_seed.json").read_text()) == {
        "teams": {"IDN": "Identity", "PAY": "Payments"}
    }
