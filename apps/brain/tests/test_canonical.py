"""Pure tests for the canonical models: ticket fields, BLOCKS links and url refs."""

import pytest
from brain.canonical import Link, WorkItem, url_ref
from pydantic import ValidationError


def ticket(**overrides) -> WorkItem:
    data = {
        "uid": "t1",
        "kind": "ticket",
        "title": "t",
        "state": "Todo",
        "created_at": "2026-05-01T00:00:00Z",
    }
    return WorkItem.model_validate({**data, **overrides})


def test_blocks_link_only_between_work_items():
    ok = Link(rel="BLOCKS", from_uid="a", from_label="WorkItem", to_uid="b", to_label="WorkItem")
    assert ok.uid == "link:BLOCKS:a->b"
    with pytest.raises(ValidationError):
        Link(rel="BLOCKS", from_uid="a", from_label="WorkItem", to_uid="s", to_label="System")


def test_url_ref_only_as_mentions_target():
    ref = url_ref("https://x/pull/1")
    Link(rel="MENTIONS", from_uid="a", from_label="WorkItem", to_uid=ref, to_label="WorkItem")
    with pytest.raises(ValidationError):
        Link(rel="CLOSES", from_uid="a", from_label="WorkItem", to_uid=ref, to_label="WorkItem")
    with pytest.raises(ValidationError):
        Link(rel="MENTIONS", from_uid=ref, from_label="WorkItem", to_uid="b", to_label="WorkItem")


def test_assignee_cannot_be_an_email():
    with pytest.raises(ValidationError):
        ticket(assignees=["a@b.co"])


@pytest.mark.parametrize(
    ("status_category", "open_"),
    [("todo", True), ("in_progress", True), ("done", False), ("canceled", False), (None, False)],
)
def test_is_open_ticket(status_category, open_):
    assert ticket(status_category=status_category).is_open_ticket() is open_
