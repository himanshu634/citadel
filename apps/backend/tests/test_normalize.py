"""Pure tests for normalize: path rules, kinds, bots, email scrubbing, the window."""

from datetime import date

import pytest
from brain.canonical import Change, Comment, Document, Person, WorkItem
from brain.config import CompanyConfig
from brain.normalize import change_kind, normalize, scrub_emails, system_for_path
from pydantic import ValidationError


def company(**overrides) -> CompanyConfig:
    data = {
        "slug": "t",
        "name": "T",
        "data_permission": "synthetic",
        "window": {"since": date(2026, 4, 15)},
        "sources": [],
        "systems": {
            "rules": [
                {"match": "src/index/**", "system": "Indexing"},
                {"match": "src/**", "system": "Core"},
            ],
            "fallback": "depth_2",
            "ignore": ["deps/**", "**/*.lock"],
        },
        "people": {"bots": ["Copilot"], "aliases": {"Alice K": "alice"}},
    }
    return CompanyConfig.model_validate({**data, **overrides})


def test_first_matching_rule_wins_then_fallback_and_ignore():
    s = company().systems
    assert system_for_path("src/index/a.c", s)[0] == "Indexing"
    assert system_for_path("src/other/b.c", s)[0] == "Core"
    assert system_for_path("tests/flow/test_x.py", s)[0] == "tests/flow"
    assert system_for_path("README.md", s)[0] == "(root)"
    assert system_for_path("deps/x/y.c", s) is None
    assert system_for_path("a/b/Cargo.lock", s) is None


@pytest.mark.parametrize(
    ("subject", "kind"),
    [
        ("fix(index): crash", "fix"),
        ("feat!: x", "feat"),
        ("chore: bump", "other"),
        ("Merge", "other"),
    ],
)
def test_change_kind(subject, kind):
    assert change_kind(subject) == kind


def test_scrub_emails():
    text = "Done.\n\nCo-authored-by: Jane Roe <jane.roe+gh@example.co.uk>"
    assert scrub_emails(text) == "Done.\n\nCo-authored-by: Jane Roe <[email]>"
    assert scrub_emails("see @alice and #12") == "see @alice and #12"


def test_person_login_cannot_be_an_email():
    with pytest.raises(ValidationError):
        Person(login="jane@example.com")


def test_normalize_scrubs_text_aliases_bots_and_window():
    when = "2026-05-01T00:00:00Z"
    records = [
        WorkItem(
            uid="w1",
            kind="issue",
            title="Mail bob@x.io",
            body="ping a@b.co",
            state="open",
            created_at=when,
            author_login="Alice K",
        ),
        WorkItem(
            uid="old",
            kind="issue",
            title="old",
            state="closed",
            created_at="2026-01-01T00:00:00Z",
            closed_at="2026-02-01T00:00:00Z",
        ),
        Comment(
            uid="c1",
            work_item_uid="w1",
            author_login="Copilot",
            created_at=when,
            body="Co-authored-by: X <x@y.com>",
        ),
        Change(
            uid="ch1",
            sha="1",
            date=when,
            subject="fix(index): a@b.co",
            author_login="bob",
            files=["src/index/a.c", "deps/z.c"],
        ),
        Document(uid="d1", path="README.md", title="Readme", body="contact: team@corp.com"),
    ]
    out = {r.uid: r for r in normalize(records, company())}

    assert "old" not in out  # before window.since
    assert out["w1"].title == "Mail [email]" and out["w1"].body == "ping [email]"
    assert out["w1"].author_login == "alice"  # alias applied
    assert out["c1"].body == "Co-authored-by: X <[email]>"
    assert out["d1"].body == "contact: [email]"
    assert out["ch1"].subject == "fix(index): [email]"
    assert out["ch1"].kind == "fix"
    assert out["ch1"].touches == {"Indexing": ["src/index/a.c"]}  # deps/ ignored
    assert out["person:copilot"].is_bot is True
    assert out["person:alice"].is_bot is False
    assert out["system:Indexing"].path_rule == "src/index/**"


def test_work_item_needs_real_activity_in_window():
    def issue(uid, **dates):
        return WorkItem(
            uid=uid,
            kind="issue",
            title=uid,
            state="open",
            created_at="2026-01-01T00:00:00Z",
            **dates,
        )

    touched = "2026-08-03T00:00:00Z"
    records = [
        issue("bulk_touched", updated_at=touched),  # relabelled by a bot: not activity
        issue("commented", updated_at=touched),
        issue("closed", updated_at=touched, closed_at="2026-05-01T00:00:00Z"),
        Comment(
            uid="c",
            work_item_uid="commented",
            author_login="bob",
            created_at="2026-06-01T00:00:00Z",
            body="still broken",
        ),
    ]
    uids = {r.uid for r in normalize(records, company())}
    assert "bulk_touched" not in uids
    assert {"commented", "closed"} <= uids


def test_system_path_rule_survives_an_earlier_mention():
    from brain.canonical import Link

    records = [
        Link(
            rel="MENTIONS",
            from_uid="w",
            from_label="WorkItem",
            to_uid="system:Indexing",
            to_label="System",
        ),
        Change(
            uid="ch", sha="1", date="2026-05-01T00:00:00Z", subject="x", files=["src/index/a.c"]
        ),
    ]
    out = {r.uid: r for r in normalize(records, company())}
    assert out["system:Indexing"].path_rule == "src/index/**"


def test_assignees_are_aliased_and_people_derived():
    item = WorkItem(
        uid="t1",
        kind="ticket",
        title="t",
        state="Todo",
        created_at="2026-05-01T00:00:00Z",
        assignees=["Alice K"],
    )
    out = list(normalize([item], company()))
    assert next(r for r in out if isinstance(r, WorkItem)).assignees == ["alice"]
    assert Person(login="alice") in [
        r.model_copy(update={"source": "unknown"}) for r in out if isinstance(r, Person)
    ]


def test_assignees_none_stays_none():
    item = WorkItem(
        uid="t1", kind="ticket", title="t", state="Todo", created_at="2026-05-01T00:00:00Z"
    )
    out = next(r for r in normalize([item], company()) if isinstance(r, WorkItem))
    assert out.assignees is None


def _old_ticket(status_category: str) -> WorkItem:
    return WorkItem(
        uid="t1",
        kind="ticket",
        title="t",
        state="x",
        status_category=status_category,
        created_at="2025-01-01T00:00:00Z",
    )


def test_open_ticket_outside_window_is_kept():
    cfg = company(window={"since": date(2026, 1, 1)})
    assert "t1" in {r.uid for r in normalize([_old_ticket("todo")], cfg)}


def test_closed_ticket_outside_window_is_dropped():
    cfg = company(window={"since": date(2026, 1, 1)})
    assert "t1" not in {r.uid for r in normalize([_old_ticket("done")], cfg)}
