"""The ticket tools against the synthetic company's ten tickets (known answers, spec section 7)."""

from __future__ import annotations

import json
from pathlib import Path

from brain import canonical as c
from brain import db, loader, schema, tools
from brain.adapters.canonical_jsonl import CanonicalJsonlAdapter
from brain.agents.toolset import Toolset
from conftest import SYNTHETIC, needs_graph, synthetic_company

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


# --- the three tools, against the synthetic tickets ---------------------------------------------


def keys(rows) -> list[str]:
    return [r.key for r in rows]


@needs_graph
def test_open_work_for_carol(ticket_graph):
    rows = tools.open_work_for(ticket_graph, "carol")
    assert keys(rows) == ["IDN-2", "IDN-3"]
    assert {t.key for t in rows[0].blocked_by} == {"IDN-1", "PAY-2"}
    assert rows[0].person_uid == "person:carol"
    assert rows[0].priority == "urgent" and rows[0].due_date == "2026-11-06"
    assert rows[0].blocks == [] and rows[1].blocked_by == []
    assert {t.key: t.assignees for t in rows[0].blocked_by} == {
        "IDN-1": ["alice"],
        "PAY-2": ["bob"],
    }


@needs_graph
def test_open_work_for_erin_sort_order(ticket_graph):
    """Priority first (high, then medium), then the due date before no due date, then key."""
    assert keys(tools.open_work_for(ticket_graph, "erin")) == ["PAY-6", "PAY-3", "PAY-4"]


@needs_graph
def test_open_work_for_alice_lists_what_it_blocks(ticket_graph):
    rows = tools.open_work_for(ticket_graph, "alice")
    assert keys(rows) == ["IDN-1"]
    assert {t.key for t in rows[0].blocks} == {"IDN-2", "PAY-4"}
    assert {t.key: t.assignees for t in rows[0].blocks} == {"IDN-2": ["carol"], "PAY-4": ["erin"]}


@needs_graph
def test_open_work_for_limit_and_unknown_person(ticket_graph):
    assert keys(tools.open_work_for(ticket_graph, "erin", limit=1)) == ["PAY-6"]
    assert tools.open_work_for(ticket_graph, "nobody") == []


@needs_graph
def test_blocked_on_carol(ticket_graph):
    rows = tools.blocked_on(ticket_graph, "carol")
    assert {(r.ticket.key, r.blocker.key, r.depth, r.via) for r in rows} == {
        ("IDN-2", "IDN-1", 1, None),
        ("IDN-2", "PAY-2", 1, None),
        ("IDN-2", "PAY-3", 2, "PAY-2"),
    }
    assert [(r.ticket.key, r.depth, r.blocker.key) for r in rows] == [
        ("IDN-2", 1, "IDN-1"),
        ("IDN-2", 1, "PAY-2"),
        ("IDN-2", 2, "PAY-3"),
    ]
    pay3 = rows[2]
    assert pay3.blocker.assignees == ["erin"]
    assert [(link.uid, link.state) for link in pay3.linked] == [("synthetic:pr:9", "open")]
    assert rows[0].linked == []


@needs_graph
def test_blocked_on_alice_is_empty(ticket_graph):
    assert tools.blocked_on(ticket_graph, "alice") == []


@needs_graph
def test_waiting_on_alice(ticket_graph):
    rows = tools.waiting_on(ticket_graph, "alice")
    assert {(r.mine.key, r.waiting.key) for r in rows} == {("IDN-1", "IDN-2"), ("IDN-1", "PAY-4")}
    assert {r.waiting.key: r.waiting.assignees for r in rows} == {
        "IDN-2": ["carol"],
        "PAY-4": ["erin"],
    }


@needs_graph
def test_waiting_on_ignores_own_tickets(ticket_graph):
    """carol's IDN-2 is blocked by others, and blocks nothing: nobody waits on her."""
    assert tools.waiting_on(ticket_graph, "carol") == []


@needs_graph
def test_ticket_rows_are_citable(ticket_graph):
    outcome = Toolset(tools.TOOLS, tools.call).call(ticket_graph, "blocked_on", {"login": "carol"})
    assert not outcome.is_error
    assert outcome.seen["synthetic:ticket:PAY-3"]["title"] == "Usage-based add-ons"
    assert "synthetic:pr:9" in outcome.seen


@needs_graph
def test_done_blocker_breaks_chain():
    """A (open, alice) <- B (done) <- C (open): the chain stops at B, so A waits on nothing."""
    slug = "test_ticket_chain"
    db.delete_graph(slug)
    schema.apply_schema(slug)

    def ticket(key: str, category: str, assignees: list[str]) -> c.WorkItem:
        return c.WorkItem(
            uid=f"t:{key}",
            kind="ticket",
            key=key,
            title=key,
            state=category,
            status_category=category,
            created_at="2026-10-01T00:00:00Z",
            assignees=assignees,
        )

    def blocks(a: str, b: str) -> c.Link:
        return c.Link(
            rel="BLOCKS",
            from_uid=f"t:{a}",
            from_label="WorkItem",
            to_uid=f"t:{b}",
            to_label="WorkItem",
            source="test",
        )

    try:
        loader.load(
            slug,
            [
                c.Person(uid=c.person_uid("alice"), login="alice"),
                c.Person(uid=c.person_uid("bob"), login="bob"),
                ticket("A", "todo", ["alice"]),
                ticket("B", "done", ["bob"]),
                ticket("C", "todo", ["bob"]),
                blocks("B", "A"),
                blocks("C", "B"),
            ],
        )
        assert tools.blocked_on(slug, "alice") == []
        assert [r.blocked_by for r in tools.open_work_for(slug, "alice")] == [[]]
        assert tools.waiting_on(slug, "bob") == []  # bob's C blocks only a done ticket
    finally:
        db.delete_graph(slug)
