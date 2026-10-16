"""Generate the synthetic company's canonical JSONL files.

Why: a tiny, fully made-up company (5 people + 1 bot, 2 teams, 4 systems, 15 work items) lets
the pipeline be demoed and tested offline. The data is shaped so each named query has a known
answer:
- Auth: alice is the expert and her team (identity) owns it -> owners and experts agree.
- Billing: bob is the expert, his team (payments) owns it -> agree.
- Web app: owned by identity, but erin (payments) made most changes -> owners_vs_experts flags it.
- Infra: owned by dave; ci-bot has more commits but is a bot -> dave is still the top expert.
- Billing and Web app are often changed together -> impact_of(Billing) ranks Web app first.

Run: `uv run python apps/backend/examples/synthetic_company/generate.py`
The JSONL files next to this script are the output; edit the data here, not the JSONL.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).parent
REPO = "synthetic/app"
WEB = "https://example.com/synthetic/app"

PEOPLE = [
    ("alice", "Alice Kim"),
    ("bob", "Bob Ortiz"),
    ("carol", "Carol Singh"),
    ("dave", "Dave Mensah"),
    ("erin", "Erin Novak"),
    ("ci-bot", "CI Bot"),
]
TEAMS = {"identity": ["alice", "carol"], "payments": ["bob", "erin"]}
OWNERSHIPS = [  # (owner_kind, owner, CODEOWNERS-style pattern)
    ("team", "identity", "/services/auth/"),
    ("team", "payments", "/services/billing/"),
    ("team", "identity", "/web/"),
    ("person", "dave", "/infra/"),
]

# number, kind, title, author, state, created, closed, body
WORK_ITEMS = [
    (
        1,
        "pull_request",
        "feat(auth): switch sessions to JWT",
        "alice",
        "merged",
        "2026-02-03",
        "2026-02-06",
        "We decided to replace server-side sessions with short-lived JWTs because the session "
        "table was the main source of DB load. Refresh tokens stay server-side. Closes #11.",
    ),
    (
        2,
        "pull_request",
        "fix(auth): refresh token rotation race",
        "alice",
        "merged",
        "2026-03-10",
        "2026-03-12",
        "Two tabs refreshing at once could revoke each other.",
    ),
    (
        3,
        "pull_request",
        "feat(billing): proration for plan changes",
        "bob",
        "merged",
        "2026-03-02",
        "2026-03-09",
        "Prorate by day, not by hour; finance confirmed day granularity is enough. Touches the "
        "plan picker in web/ too. Closes #12.",
    ),
    (
        4,
        "pull_request",
        "perf(billing): batch invoice generation",
        "bob",
        "merged",
        "2026-04-14",
        "2026-04-20",
        "Generate invoices in batches of 500 instead of one by one.",
    ),
    (
        5,
        "pull_request",
        "feat(web): new checkout page",
        "erin",
        "merged",
        "2026-05-05",
        "2026-05-15",
        "Rebuilt checkout on the new design system. Billing API unchanged. Closes #13.",
    ),
    (
        6,
        "pull_request",
        "fix(web): login redirect loop",
        "erin",
        "merged",
        "2026-06-01",
        "2026-06-03",
        "Redirect loop when JWT expired mid-session (see #1).",
    ),
    (
        7,
        "pull_request",
        "ci: cache dependencies in pipeline",
        "dave",
        "merged",
        "2026-04-02",
        "2026-04-03",
        "Cuts CI time by about 40%.",
    ),
    (
        8,
        "pull_request",
        "build(infra): move to managed Postgres",
        "dave",
        "merged",
        "2026-07-01",
        "2026-07-10",
        "Per ADR-001 we move to managed Postgres. Self-hosted backups were unreliable.",
    ),
    (
        9,
        "pull_request",
        "feat(billing): usage-based add-ons",
        "erin",
        "open",
        "2026-08-20",
        None,
        "Adds metered add-ons; UI in web/billing. Draft, needs review.",
    ),
    (
        10,
        "pull_request",
        "refactor(auth): extract token service",
        "carol",
        "merged",
        "2026-09-01",
        "2026-09-05",
        "Pure refactor, no behaviour change.",
    ),
    (
        11,
        "issue",
        "Session table causes DB load spikes",
        "dave",
        "closed",
        "2026-01-28",
        "2026-02-06",
        "p95 DB CPU hits 90% at login peaks; sessions table is hot.",
    ),
    (
        12,
        "issue",
        "Customers overcharged on mid-month upgrades",
        "bob",
        "closed",
        "2026-02-25",
        "2026-03-09",
        "Support tickets: upgrades are charged a full month.",
    ),
    (
        13,
        "issue",
        "Checkout page is slow on mobile",
        "carol",
        "closed",
        "2026-04-28",
        "2026-05-15",
        "LCP over 4s on mid-range phones.",
    ),
    (
        14,
        "issue",
        "Invoice emails sometimes sent twice",
        "erin",
        "open",
        "2026-09-10",
        None,
        "Seen twice this month; may be the batch job retrying.",
    ),
]
THREAD = {
    "uid": "synthetic:slack:thread:eng-2026-07-15",
    "title": "#eng: should billing own the checkout page?",
    "author": "bob",
    "created": "2026-07-15",
    "body": "erin has done most of the checkout work lately but CODEOWNERS still says identity "
    "owns web/. Proposal: move web/checkout to payments. No decision yet.",
}
CLOSES = [(1, 11), (3, 12), (5, 13)]
MENTIONS = [(6, 1), (9, 3)]

# sha, pr, author, date, subject, files
CHANGES = [
    ("a001", 1, "alice", "2026-02-04", "feat(auth): add JWT issuer", ["services/auth/jwt.py"]),
    (
        "a002",
        1,
        "alice",
        "2026-02-05",
        "feat(auth): drop session table usage",
        ["services/auth/session.py", "services/auth/jwt.py"],
    ),
    (
        "a003",
        1,
        "alice",
        "2026-02-05",
        "feat(auth): login page uses JWT",
        ["services/auth/login.py", "web/login/page.tsx"],
    ),
    (
        "a004",
        2,
        "alice",
        "2026-03-11",
        "fix(auth): lock refresh rotation",
        ["services/auth/refresh.py"],
    ),
    (
        "a005",
        2,
        "alice",
        "2026-03-12",
        "test(auth): rotation race test",
        ["services/auth/tests/test_refresh.py"],
    ),
    (
        "b001",
        3,
        "bob",
        "2026-03-03",
        "feat(billing): proration engine",
        ["services/billing/proration.py"],
    ),
    (
        "b002",
        3,
        "bob",
        "2026-03-05",
        "feat(billing): plan picker shows prorated price",
        ["services/billing/api.py", "web/billing/plan_picker.tsx"],
    ),
    (
        "b003",
        3,
        "bob",
        "2026-03-08",
        "fix(billing): rounding in proration",
        ["services/billing/proration.py"],
    ),
    (
        "b004",
        4,
        "bob",
        "2026-04-15",
        "perf(billing): batch invoices",
        ["services/billing/invoices.py"],
    ),
    (
        "b005",
        4,
        "bob",
        "2026-04-18",
        "perf(billing): invoice query index",
        ["services/billing/invoices.py", "infra/db/migrations/0042.sql"],
    ),
    (
        "e001",
        5,
        "erin",
        "2026-05-06",
        "feat(web): checkout layout",
        ["web/checkout/page.tsx", "web/checkout/styles.css"],
    ),
    (
        "e002",
        5,
        "erin",
        "2026-05-09",
        "feat(web): checkout calls billing quote API",
        ["web/checkout/page.tsx", "services/billing/api.py"],
    ),
    (
        "e003",
        5,
        "erin",
        "2026-05-14",
        "perf(web): lazy-load payment widget",
        ["web/checkout/payment.tsx"],
    ),
    (
        "e004",
        6,
        "erin",
        "2026-06-02",
        "fix(web): handle expired JWT on login",
        ["web/login/page.tsx"],
    ),
    (
        "e005",
        9,
        "erin",
        "2026-08-21",
        "feat(billing): metered add-ons model",
        ["services/billing/addons.py", "web/billing/addons.tsx"],
    ),
    ("e006", 9, "erin", "2026-08-25", "feat(web): add-ons UI", ["web/billing/addons.tsx"]),
    ("d001", 7, "dave", "2026-04-02", "ci: cache deps", ["infra/ci/pipeline.yml"]),
    (
        "d002",
        8,
        "dave",
        "2026-07-03",
        "build(infra): managed Postgres terraform",
        ["infra/terraform/db.tf"],
    ),
    (
        "c001",
        10,
        "carol",
        "2026-09-02",
        "refactor(auth): token service module",
        ["services/auth/tokens.py", "services/auth/jwt.py"],
    ),
    ("c002", 10, "carol", "2026-09-04", "docs(web): login flow notes", ["web/login/README.md"]),
    # bot noise: more Infra commits than dave, but bots are excluded from expertise
    (
        "z001",
        None,
        "ci-bot",
        "2026-03-01",
        "build: bump base image",
        ["infra/docker/base.Dockerfile"],
    ),
    (
        "z002",
        None,
        "ci-bot",
        "2026-05-01",
        "build: bump base image",
        ["infra/docker/base.Dockerfile"],
    ),
    (
        "z003",
        None,
        "ci-bot",
        "2026-07-01",
        "build: bump base image",
        ["infra/docker/base.Dockerfile"],
    ),
    (
        "z004",
        None,
        "ci-bot",
        "2026-09-01",
        "build: bump base image",
        ["infra/docker/base.Dockerfile"],
    ),
    ("z005", None, "ci-bot", "2026-09-15", "chore: update lockfile", ["web/package.lock"]),
]

# pr, reviewer, state, date
REVIEWS = [
    (1, "carol", "APPROVED", "2026-02-06"),
    (1, "dave", "COMMENTED", "2026-02-05"),
    (2, "carol", "APPROVED", "2026-03-12"),
    (3, "erin", "CHANGES_REQUESTED", "2026-03-06"),
    (3, "erin", "APPROVED", "2026-03-09"),
    (4, "erin", "APPROVED", "2026-04-20"),
    (5, "bob", "APPROVED", "2026-05-15"),
    (5, "carol", "COMMENTED", "2026-05-12"),
    (6, "alice", "APPROVED", "2026-06-03"),
    (7, "bob", "APPROVED", "2026-04-03"),
    (8, "alice", "APPROVED", "2026-07-09"),
    (10, "alice", "APPROVED", "2026-09-05"),
]

# pr/issue number, author, date, body
COMMENTS = [
    (1, "dave", "2026-02-05", "Does this remove the sessions table entirely? Ops wants it gone."),
    (1, "alice", "2026-02-05", "Yes after one release; refresh tokens move to their own table."),
    (3, "erin", "2026-03-06", "Rounding is off by a cent for annual plans."),
    (3, "bob", "2026-03-08", "Fixed in b003; we round half-up per finance."),
    (5, "carol", "2026-05-12", "Looks good; identity should still review login-adjacent bits."),
    (8, "alice", "2026-07-09", "Make sure the auth service connection pool is resized."),
    (14, "bob", "2026-09-11", "Probably the batch retry from #4; needs an idempotency key."),
]

DOCUMENTS = [
    (
        "docs/auth-design.md",
        "Auth design",
        "alice",
        "2026-02-10",
        "# Auth design\n\nWe use short-lived JWTs (15 min) and server-side refresh tokens. "
        "Decision made in #1 after the DB load issue #11. Code: services/auth.",
    ),
    (
        "docs/billing-runbook.md",
        "Billing runbook",
        "bob",
        "2026-04-22",
        "# Billing runbook\n\nInvoices are generated in batches of 500 (#4). If invoices are "
        "duplicated, check the batch retry. Code: services/billing.",
    ),
    (
        "docs/adr/001-managed-postgres.md",
        "ADR-001: Managed Postgres",
        "dave",
        "2026-06-20",
        "# ADR-001: Managed Postgres\n\nStatus: accepted. Self-hosted backups failed twice. "
        "We move to managed Postgres (#8). Code: infra/terraform.",
    ),
]
DOC_MENTIONS = [  # (doc path, work item number or system name)
    ("docs/auth-design.md", 1),
    ("docs/auth-design.md", 11),
    ("docs/auth-design.md", "Auth"),
    ("docs/billing-runbook.md", 4),
    ("docs/billing-runbook.md", "Billing"),
    ("docs/adr/001-managed-postgres.md", 8),
    ("docs/adr/001-managed-postgres.md", "Infra"),
]


def wi_uid(number: int) -> str:
    kind = next(k for n, k, *_ in WORK_ITEMS if n == number)
    return f"synthetic:{'pr' if kind == 'pull_request' else 'issue'}:{number}"


def wi_url(number: int) -> str:
    kind = next(k for n, k, *_ in WORK_ITEMS if n == number)
    return f"{WEB}/{'pull' if kind == 'pull_request' else 'issues'}/{number}"


def ts(day: str) -> str:
    return f"{day}T12:00:00Z"


def write(name: str, rows: list[dict]) -> None:
    with (OUT / name).open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    print(f"{name}: {len(rows)}")


def main() -> None:
    write("people.jsonl", [{"login": lg, "display_name": dn} for lg, dn in PEOPLE])
    write("teams.jsonl", [{"name": t} for t in TEAMS])
    write(
        "ownerships.jsonl",
        [
            {
                "uid": f"synthetic:codeowners:{i}",
                "owner_kind": k,
                "owner": o,
                "pattern": p,
                "url": f"{WEB}/blob/main/CODEOWNERS",
            }
            for i, (k, o, p) in enumerate(OWNERSHIPS, start=1)
        ],
    )
    items = [
        {
            "uid": wi_uid(n),
            "kind": k,
            "number": n,
            "title": t,
            "body": b,
            "state": s,
            "author_login": a,
            "created_at": ts(c),
            "closed_at": ts(cl) if cl else None,
            "merged_at": ts(cl) if s == "merged" else None,
            "container": REPO,
            "url": wi_url(n),
        }
        for n, k, t, a, s, c, cl, b in WORK_ITEMS
    ]
    items.append(
        {
            "uid": THREAD["uid"],
            "kind": "thread",
            "title": THREAD["title"],
            "body": THREAD["body"],
            "state": "open",
            "author_login": THREAD["author"],
            "created_at": ts(THREAD["created"]),
            "container": "slack:#eng",
            "source": "slack_export",
        }
    )
    write("work_items.jsonl", items)
    write(
        "changes.jsonl",
        [
            {
                "uid": f"synthetic:commit:{sha}",
                "sha": sha,
                "date": ts(d),
                "author_login": a,
                "subject": s,
                "files": f,
                "url": f"{WEB}/commit/{sha}",
            }
            for sha, _, a, d, s, f in CHANGES
        ],
    )
    write(
        "reviews.jsonl",
        [
            {
                "uid": f"synthetic:review:{n}:{r}:{d}",
                "work_item_uid": wi_uid(n),
                "reviewer_login": r,
                "state": st,
                "submitted_at": ts(d),
                "url": wi_url(n),
            }
            for n, r, st, d in REVIEWS
        ],
    )
    write(
        "comments.jsonl",
        [
            {
                "uid": f"synthetic:comment:{i}",
                "work_item_uid": wi_uid(n),
                "author_login": a,
                "created_at": ts(d),
                "body": b,
                "url": f"{wi_url(n)}#comment-{i}",
            }
            for i, (n, a, d, b) in enumerate(COMMENTS, start=1)
        ],
    )
    write(
        "documents.jsonl",
        [
            {
                "uid": f"synthetic:doc:{p}",
                "path": p,
                "title": t,
                "author_login": a,
                "updated_at": ts(d),
                "body": b,
                "url": f"{WEB}/blob/main/{p}",
            }
            for p, t, a, d, b in DOCUMENTS
        ],
    )
    links = []
    for team, members in TEAMS.items():
        links += [
            {
                "rel": "MEMBER_OF",
                "from_label": "Person",
                "from_uid": f"person:{m}",
                "to_label": "Team",
                "to_uid": f"team:{team}",
            }
            for m in members
        ]
    links += [
        {
            "rel": "CLOSES",
            "from_label": "WorkItem",
            "from_uid": wi_uid(pr),
            "to_label": "WorkItem",
            "to_uid": wi_uid(issue),
        }
        for pr, issue in CLOSES
    ]
    links += [
        {
            "rel": "MENTIONS",
            "from_label": "WorkItem",
            "from_uid": wi_uid(a),
            "to_label": "WorkItem",
            "to_uid": wi_uid(b),
        }
        for a, b in MENTIONS
    ]
    links += [
        {
            "rel": "PART_OF",
            "from_label": "Change",
            "from_uid": f"synthetic:commit:{sha}",
            "to_label": "WorkItem",
            "to_uid": wi_uid(pr),
        }
        for sha, pr, *_ in CHANGES
        if pr
    ]
    for path, target in DOC_MENTIONS:
        to_label, to_uid = (
            ("System", f"system:{target}")
            if isinstance(target, str)
            else ("WorkItem", wi_uid(target))
        )
        links.append(
            {
                "rel": "MENTIONS",
                "from_label": "Document",
                "from_uid": f"synthetic:doc:{path}",
                "to_label": to_label,
                "to_uid": to_uid,
            }
        )
    write("links.jsonl", links)


if __name__ == "__main__":
    main()
