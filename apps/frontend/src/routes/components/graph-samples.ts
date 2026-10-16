// The synthetic company's graph view, bots shown, for the gallery: a fresh load of
// apps/backend/examples/synthetic_company read through brain.graph_view (bots=True).
import type { GraphView } from '$lib/types';

export const syntheticGraph: GraphView = {
 "slug": "synthetic",
 "nodes": [
  {
   "uid": "person:alice",
   "label": "Person",
   "title": "alice",
   "kind": null,
   "state": null,
   "number": null,
   "url": null,
   "is_bot": false,
   "comments": 0,
   "degree": 14,
   "territory": "system:Auth"
  },
  {
   "uid": "person:bob",
   "label": "Person",
   "title": "bob",
   "kind": null,
   "state": null,
   "number": null,
   "url": null,
   "is_bot": false,
   "comments": 0,
   "degree": 15,
   "territory": "system:Billing"
  },
  {
   "uid": "person:carol",
   "label": "Person",
   "title": "carol",
   "kind": null,
   "state": null,
   "number": null,
   "url": null,
   "is_bot": false,
   "comments": 0,
   "degree": 9,
   "territory": "system:Auth"
  },
  {
   "uid": "person:ci-bot",
   "label": "Person",
   "title": "ci-bot",
   "kind": null,
   "state": null,
   "number": null,
   "url": null,
   "is_bot": true,
   "comments": 0,
   "degree": 5,
   "territory": "system:Infra"
  },
  {
   "uid": "person:dave",
   "label": "Person",
   "title": "dave",
   "kind": null,
   "state": null,
   "number": null,
   "url": null,
   "is_bot": false,
   "comments": 0,
   "degree": 9,
   "territory": "system:Infra"
  },
  {
   "uid": "person:erin",
   "label": "Person",
   "title": "erin",
   "kind": null,
   "state": null,
   "number": null,
   "url": null,
   "is_bot": false,
   "comments": 0,
   "degree": 14,
   "territory": "system:Billing"
  },
  {
   "uid": "synthetic:commit:a001",
   "label": "Change",
   "title": "feat(auth): add JWT issuer",
   "kind": "feat",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/a001",
   "is_bot": false,
   "comments": 0,
   "degree": 3,
   "territory": "system:Auth"
  },
  {
   "uid": "synthetic:commit:a002",
   "label": "Change",
   "title": "feat(auth): drop session table usage",
   "kind": "feat",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/a002",
   "is_bot": false,
   "comments": 0,
   "degree": 3,
   "territory": "system:Auth"
  },
  {
   "uid": "synthetic:commit:a003",
   "label": "Change",
   "title": "feat(auth): login page uses JWT",
   "kind": "feat",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/a003",
   "is_bot": false,
   "comments": 0,
   "degree": 4,
   "territory": "system:Auth"
  },
  {
   "uid": "synthetic:commit:a004",
   "label": "Change",
   "title": "fix(auth): lock refresh rotation",
   "kind": "fix",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/a004",
   "is_bot": false,
   "comments": 0,
   "degree": 3,
   "territory": "system:Auth"
  },
  {
   "uid": "synthetic:commit:a005",
   "label": "Change",
   "title": "test(auth): rotation race test",
   "kind": "other",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/a005",
   "is_bot": false,
   "comments": 0,
   "degree": 3,
   "territory": "system:Auth"
  },
  {
   "uid": "synthetic:commit:b001",
   "label": "Change",
   "title": "feat(billing): proration engine",
   "kind": "feat",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/b001",
   "is_bot": false,
   "comments": 0,
   "degree": 3,
   "territory": "system:Billing"
  },
  {
   "uid": "synthetic:commit:b002",
   "label": "Change",
   "title": "feat(billing): plan picker shows prorated price",
   "kind": "feat",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/b002",
   "is_bot": false,
   "comments": 0,
   "degree": 4,
   "territory": "system:Billing"
  },
  {
   "uid": "synthetic:commit:b003",
   "label": "Change",
   "title": "fix(billing): rounding in proration",
   "kind": "fix",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/b003",
   "is_bot": false,
   "comments": 0,
   "degree": 3,
   "territory": "system:Billing"
  },
  {
   "uid": "synthetic:commit:b004",
   "label": "Change",
   "title": "perf(billing): batch invoices",
   "kind": "perf",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/b004",
   "is_bot": false,
   "comments": 0,
   "degree": 3,
   "territory": "system:Billing"
  },
  {
   "uid": "synthetic:commit:b005",
   "label": "Change",
   "title": "perf(billing): invoice query index",
   "kind": "perf",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/b005",
   "is_bot": false,
   "comments": 0,
   "degree": 4,
   "territory": "system:Billing"
  },
  {
   "uid": "synthetic:commit:c001",
   "label": "Change",
   "title": "refactor(auth): token service module",
   "kind": "refactor",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/c001",
   "is_bot": false,
   "comments": 0,
   "degree": 3,
   "territory": "system:Auth"
  },
  {
   "uid": "synthetic:commit:c002",
   "label": "Change",
   "title": "docs(web): login flow notes",
   "kind": "docs",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/c002",
   "is_bot": false,
   "comments": 0,
   "degree": 3,
   "territory": "system:Web app"
  },
  {
   "uid": "synthetic:commit:d001",
   "label": "Change",
   "title": "ci: cache deps",
   "kind": "ci",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/d001",
   "is_bot": false,
   "comments": 0,
   "degree": 3,
   "territory": "system:Infra"
  },
  {
   "uid": "synthetic:commit:d002",
   "label": "Change",
   "title": "build(infra): managed Postgres terraform",
   "kind": "build",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/d002",
   "is_bot": false,
   "comments": 0,
   "degree": 3,
   "territory": "system:Infra"
  },
  {
   "uid": "synthetic:commit:e001",
   "label": "Change",
   "title": "feat(web): checkout layout",
   "kind": "feat",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/e001",
   "is_bot": false,
   "comments": 0,
   "degree": 3,
   "territory": "system:Web app"
  },
  {
   "uid": "synthetic:commit:e002",
   "label": "Change",
   "title": "feat(web): checkout calls billing quote API",
   "kind": "feat",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/e002",
   "is_bot": false,
   "comments": 0,
   "degree": 4,
   "territory": "system:Billing"
  },
  {
   "uid": "synthetic:commit:e003",
   "label": "Change",
   "title": "perf(web): lazy-load payment widget",
   "kind": "perf",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/e003",
   "is_bot": false,
   "comments": 0,
   "degree": 3,
   "territory": "system:Web app"
  },
  {
   "uid": "synthetic:commit:e004",
   "label": "Change",
   "title": "fix(web): handle expired JWT on login",
   "kind": "fix",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/e004",
   "is_bot": false,
   "comments": 0,
   "degree": 3,
   "territory": "system:Web app"
  },
  {
   "uid": "synthetic:commit:e005",
   "label": "Change",
   "title": "feat(billing): metered add-ons model",
   "kind": "feat",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/e005",
   "is_bot": false,
   "comments": 0,
   "degree": 4,
   "territory": "system:Billing"
  },
  {
   "uid": "synthetic:commit:e006",
   "label": "Change",
   "title": "feat(web): add-ons UI",
   "kind": "feat",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/e006",
   "is_bot": false,
   "comments": 0,
   "degree": 3,
   "territory": "system:Web app"
  },
  {
   "uid": "synthetic:commit:z001",
   "label": "Change",
   "title": "build: bump base image",
   "kind": "build",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/z001",
   "is_bot": false,
   "comments": 0,
   "degree": 2,
   "territory": "system:Infra"
  },
  {
   "uid": "synthetic:commit:z002",
   "label": "Change",
   "title": "build: bump base image",
   "kind": "build",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/z002",
   "is_bot": false,
   "comments": 0,
   "degree": 2,
   "territory": "system:Infra"
  },
  {
   "uid": "synthetic:commit:z003",
   "label": "Change",
   "title": "build: bump base image",
   "kind": "build",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/z003",
   "is_bot": false,
   "comments": 0,
   "degree": 2,
   "territory": "system:Infra"
  },
  {
   "uid": "synthetic:commit:z004",
   "label": "Change",
   "title": "build: bump base image",
   "kind": "build",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/z004",
   "is_bot": false,
   "comments": 0,
   "degree": 2,
   "territory": "system:Infra"
  },
  {
   "uid": "synthetic:commit:z005",
   "label": "Change",
   "title": "chore: update lockfile",
   "kind": "other",
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/commit/z005",
   "is_bot": false,
   "comments": 0,
   "degree": 1,
   "territory": "none"
  },
  {
   "uid": "synthetic:doc:docs/adr/001-managed-postgres.md",
   "label": "Document",
   "title": "ADR-001: Managed Postgres",
   "kind": null,
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/blob/main/docs/adr/001-managed-postgres.md",
   "is_bot": false,
   "comments": 0,
   "degree": 3,
   "territory": "system:Infra"
  },
  {
   "uid": "synthetic:doc:docs/auth-design.md",
   "label": "Document",
   "title": "Auth design",
   "kind": null,
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/blob/main/docs/auth-design.md",
   "is_bot": false,
   "comments": 0,
   "degree": 4,
   "territory": "system:Auth"
  },
  {
   "uid": "synthetic:doc:docs/billing-runbook.md",
   "label": "Document",
   "title": "Billing runbook",
   "kind": null,
   "state": null,
   "number": null,
   "url": "https://example.com/synthetic/app/blob/main/docs/billing-runbook.md",
   "is_bot": false,
   "comments": 0,
   "degree": 3,
   "territory": "system:Billing"
  },
  {
   "uid": "synthetic:issue:11",
   "label": "WorkItem",
   "title": "Session table causes DB load spikes",
   "kind": "issue",
   "state": "closed",
   "number": 11,
   "url": "https://example.com/synthetic/app/issues/11",
   "is_bot": false,
   "comments": 0,
   "degree": 3,
   "territory": "system:Auth"
  },
  {
   "uid": "synthetic:issue:12",
   "label": "WorkItem",
   "title": "Customers overcharged on mid-month upgrades",
   "kind": "issue",
   "state": "closed",
   "number": 12,
   "url": "https://example.com/synthetic/app/issues/12",
   "is_bot": false,
   "comments": 0,
   "degree": 2,
   "territory": "system:Billing"
  },
  {
   "uid": "synthetic:issue:13",
   "label": "WorkItem",
   "title": "Checkout page is slow on mobile",
   "kind": "issue",
   "state": "closed",
   "number": 13,
   "url": "https://example.com/synthetic/app/issues/13",
   "is_bot": false,
   "comments": 0,
   "degree": 2,
   "territory": "system:Web app"
  },
  {
   "uid": "synthetic:issue:14",
   "label": "WorkItem",
   "title": "Invoice emails sometimes sent twice",
   "kind": "issue",
   "state": "open",
   "number": 14,
   "url": "https://example.com/synthetic/app/issues/14",
   "is_bot": false,
   "comments": 1,
   "degree": 2,
   "territory": "none"
  },
  {
   "uid": "synthetic:pr:1",
   "label": "WorkItem",
   "title": "feat(auth): switch sessions to JWT",
   "kind": "pull_request",
   "state": "merged",
   "number": 1,
   "url": "https://example.com/synthetic/app/pull/1",
   "is_bot": false,
   "comments": 2,
   "degree": 11,
   "territory": "system:Auth"
  },
  {
   "uid": "synthetic:pr:10",
   "label": "WorkItem",
   "title": "refactor(auth): extract token service",
   "kind": "pull_request",
   "state": "merged",
   "number": 10,
   "url": "https://example.com/synthetic/app/pull/10",
   "is_bot": false,
   "comments": 0,
   "degree": 4,
   "territory": "system:Auth"
  },
  {
   "uid": "synthetic:pr:2",
   "label": "WorkItem",
   "title": "fix(auth): refresh token rotation race",
   "kind": "pull_request",
   "state": "merged",
   "number": 2,
   "url": "https://example.com/synthetic/app/pull/2",
   "is_bot": false,
   "comments": 0,
   "degree": 4,
   "territory": "system:Auth"
  },
  {
   "uid": "synthetic:pr:3",
   "label": "WorkItem",
   "title": "feat(billing): proration for plan changes",
   "kind": "pull_request",
   "state": "merged",
   "number": 3,
   "url": "https://example.com/synthetic/app/pull/3",
   "is_bot": false,
   "comments": 2,
   "degree": 9,
   "territory": "system:Billing"
  },
  {
   "uid": "synthetic:pr:4",
   "label": "WorkItem",
   "title": "perf(billing): batch invoice generation",
   "kind": "pull_request",
   "state": "merged",
   "number": 4,
   "url": "https://example.com/synthetic/app/pull/4",
   "is_bot": false,
   "comments": 0,
   "degree": 5,
   "territory": "system:Billing"
  },
  {
   "uid": "synthetic:pr:5",
   "label": "WorkItem",
   "title": "feat(web): new checkout page",
   "kind": "pull_request",
   "state": "merged",
   "number": 5,
   "url": "https://example.com/synthetic/app/pull/5",
   "is_bot": false,
   "comments": 1,
   "degree": 8,
   "territory": "system:Web app"
  },
  {
   "uid": "synthetic:pr:6",
   "label": "WorkItem",
   "title": "fix(web): login redirect loop",
   "kind": "pull_request",
   "state": "merged",
   "number": 6,
   "url": "https://example.com/synthetic/app/pull/6",
   "is_bot": false,
   "comments": 0,
   "degree": 4,
   "territory": "system:Web app"
  },
  {
   "uid": "synthetic:pr:7",
   "label": "WorkItem",
   "title": "ci: cache dependencies in pipeline",
   "kind": "pull_request",
   "state": "merged",
   "number": 7,
   "url": "https://example.com/synthetic/app/pull/7",
   "is_bot": false,
   "comments": 0,
   "degree": 3,
   "territory": "system:Infra"
  },
  {
   "uid": "synthetic:pr:8",
   "label": "WorkItem",
   "title": "build(infra): move to managed Postgres",
   "kind": "pull_request",
   "state": "merged",
   "number": 8,
   "url": "https://example.com/synthetic/app/pull/8",
   "is_bot": false,
   "comments": 1,
   "degree": 5,
   "territory": "system:Infra"
  },
  {
   "uid": "synthetic:pr:9",
   "label": "WorkItem",
   "title": "feat(billing): usage-based add-ons",
   "kind": "pull_request",
   "state": "open",
   "number": 9,
   "url": "https://example.com/synthetic/app/pull/9",
   "is_bot": false,
   "comments": 0,
   "degree": 4,
   "territory": "system:Billing"
  },
  {
   "uid": "synthetic:slack:thread:eng-2026-07-15",
   "label": "WorkItem",
   "title": "#eng: should billing own the checkout page?",
   "kind": "thread",
   "state": "open",
   "number": null,
   "url": null,
   "is_bot": false,
   "comments": 0,
   "degree": 1,
   "territory": "none"
  },
  {
   "uid": "system:Auth",
   "label": "System",
   "title": "Auth",
   "kind": null,
   "state": null,
   "number": null,
   "url": null,
   "is_bot": false,
   "comments": 0,
   "degree": 8,
   "territory": "system:Auth"
  },
  {
   "uid": "system:Billing",
   "label": "System",
   "title": "Billing",
   "kind": null,
   "state": null,
   "number": null,
   "url": null,
   "is_bot": false,
   "comments": 0,
   "degree": 9,
   "territory": "system:Billing"
  },
  {
   "uid": "system:Infra",
   "label": "System",
   "title": "Infra",
   "kind": null,
   "state": null,
   "number": null,
   "url": null,
   "is_bot": false,
   "comments": 0,
   "degree": 9,
   "territory": "system:Infra"
  },
  {
   "uid": "system:Web app",
   "label": "System",
   "title": "Web app",
   "kind": null,
   "state": null,
   "number": null,
   "url": null,
   "is_bot": false,
   "comments": 0,
   "degree": 10,
   "territory": "system:Web app"
  },
  {
   "uid": "team:identity",
   "label": "Team",
   "title": "identity",
   "kind": null,
   "state": null,
   "number": null,
   "url": null,
   "is_bot": false,
   "comments": 0,
   "degree": 4,
   "territory": "system:Auth"
  },
  {
   "uid": "team:payments",
   "label": "Team",
   "title": "payments",
   "kind": null,
   "state": null,
   "number": null,
   "url": null,
   "is_bot": false,
   "comments": 0,
   "degree": 3,
   "territory": "system:Billing"
  }
 ],
 "edges": [
  {
   "source": "person:alice",
   "rel": "AUTHORED",
   "target": "synthetic:commit:a001"
  },
  {
   "source": "person:alice",
   "rel": "AUTHORED",
   "target": "synthetic:commit:a002"
  },
  {
   "source": "person:alice",
   "rel": "AUTHORED",
   "target": "synthetic:commit:a003"
  },
  {
   "source": "person:alice",
   "rel": "AUTHORED",
   "target": "synthetic:commit:a004"
  },
  {
   "source": "person:alice",
   "rel": "AUTHORED",
   "target": "synthetic:commit:a005"
  },
  {
   "source": "person:alice",
   "rel": "AUTHORED",
   "target": "synthetic:doc:docs/auth-design.md"
  },
  {
   "source": "person:alice",
   "rel": "AUTHORED",
   "target": "synthetic:pr:1"
  },
  {
   "source": "person:alice",
   "rel": "AUTHORED",
   "target": "synthetic:pr:2"
  },
  {
   "source": "person:alice",
   "rel": "COMMENTED_ON",
   "target": "synthetic:pr:1"
  },
  {
   "source": "person:alice",
   "rel": "COMMENTED_ON",
   "target": "synthetic:pr:8"
  },
  {
   "source": "person:alice",
   "rel": "MEMBER_OF",
   "target": "team:identity"
  },
  {
   "source": "person:alice",
   "rel": "REVIEWED",
   "target": "synthetic:pr:10"
  },
  {
   "source": "person:alice",
   "rel": "REVIEWED",
   "target": "synthetic:pr:6"
  },
  {
   "source": "person:alice",
   "rel": "REVIEWED",
   "target": "synthetic:pr:8"
  },
  {
   "source": "person:bob",
   "rel": "AUTHORED",
   "target": "synthetic:commit:b001"
  },
  {
   "source": "person:bob",
   "rel": "AUTHORED",
   "target": "synthetic:commit:b002"
  },
  {
   "source": "person:bob",
   "rel": "AUTHORED",
   "target": "synthetic:commit:b003"
  },
  {
   "source": "person:bob",
   "rel": "AUTHORED",
   "target": "synthetic:commit:b004"
  },
  {
   "source": "person:bob",
   "rel": "AUTHORED",
   "target": "synthetic:commit:b005"
  },
  {
   "source": "person:bob",
   "rel": "AUTHORED",
   "target": "synthetic:doc:docs/billing-runbook.md"
  },
  {
   "source": "person:bob",
   "rel": "AUTHORED",
   "target": "synthetic:issue:12"
  },
  {
   "source": "person:bob",
   "rel": "AUTHORED",
   "target": "synthetic:pr:3"
  },
  {
   "source": "person:bob",
   "rel": "AUTHORED",
   "target": "synthetic:pr:4"
  },
  {
   "source": "person:bob",
   "rel": "AUTHORED",
   "target": "synthetic:slack:thread:eng-2026-07-15"
  },
  {
   "source": "person:bob",
   "rel": "COMMENTED_ON",
   "target": "synthetic:issue:14"
  },
  {
   "source": "person:bob",
   "rel": "COMMENTED_ON",
   "target": "synthetic:pr:3"
  },
  {
   "source": "person:bob",
   "rel": "MEMBER_OF",
   "target": "team:payments"
  },
  {
   "source": "person:bob",
   "rel": "REVIEWED",
   "target": "synthetic:pr:5"
  },
  {
   "source": "person:bob",
   "rel": "REVIEWED",
   "target": "synthetic:pr:7"
  },
  {
   "source": "person:carol",
   "rel": "AUTHORED",
   "target": "synthetic:commit:c001"
  },
  {
   "source": "person:carol",
   "rel": "AUTHORED",
   "target": "synthetic:commit:c002"
  },
  {
   "source": "person:carol",
   "rel": "AUTHORED",
   "target": "synthetic:issue:13"
  },
  {
   "source": "person:carol",
   "rel": "AUTHORED",
   "target": "synthetic:pr:10"
  },
  {
   "source": "person:carol",
   "rel": "COMMENTED_ON",
   "target": "synthetic:pr:5"
  },
  {
   "source": "person:carol",
   "rel": "MEMBER_OF",
   "target": "team:identity"
  },
  {
   "source": "person:carol",
   "rel": "REVIEWED",
   "target": "synthetic:pr:1"
  },
  {
   "source": "person:carol",
   "rel": "REVIEWED",
   "target": "synthetic:pr:2"
  },
  {
   "source": "person:carol",
   "rel": "REVIEWED",
   "target": "synthetic:pr:5"
  },
  {
   "source": "person:ci-bot",
   "rel": "AUTHORED",
   "target": "synthetic:commit:z001"
  },
  {
   "source": "person:ci-bot",
   "rel": "AUTHORED",
   "target": "synthetic:commit:z002"
  },
  {
   "source": "person:ci-bot",
   "rel": "AUTHORED",
   "target": "synthetic:commit:z003"
  },
  {
   "source": "person:ci-bot",
   "rel": "AUTHORED",
   "target": "synthetic:commit:z004"
  },
  {
   "source": "person:ci-bot",
   "rel": "AUTHORED",
   "target": "synthetic:commit:z005"
  },
  {
   "source": "person:dave",
   "rel": "AUTHORED",
   "target": "synthetic:commit:d001"
  },
  {
   "source": "person:dave",
   "rel": "AUTHORED",
   "target": "synthetic:commit:d002"
  },
  {
   "source": "person:dave",
   "rel": "AUTHORED",
   "target": "synthetic:doc:docs/adr/001-managed-postgres.md"
  },
  {
   "source": "person:dave",
   "rel": "AUTHORED",
   "target": "synthetic:issue:11"
  },
  {
   "source": "person:dave",
   "rel": "AUTHORED",
   "target": "synthetic:pr:7"
  },
  {
   "source": "person:dave",
   "rel": "AUTHORED",
   "target": "synthetic:pr:8"
  },
  {
   "source": "person:dave",
   "rel": "COMMENTED_ON",
   "target": "synthetic:pr:1"
  },
  {
   "source": "person:dave",
   "rel": "OWNS",
   "target": "system:Infra"
  },
  {
   "source": "person:dave",
   "rel": "REVIEWED",
   "target": "synthetic:pr:1"
  },
  {
   "source": "person:erin",
   "rel": "AUTHORED",
   "target": "synthetic:commit:e001"
  },
  {
   "source": "person:erin",
   "rel": "AUTHORED",
   "target": "synthetic:commit:e002"
  },
  {
   "source": "person:erin",
   "rel": "AUTHORED",
   "target": "synthetic:commit:e003"
  },
  {
   "source": "person:erin",
   "rel": "AUTHORED",
   "target": "synthetic:commit:e004"
  },
  {
   "source": "person:erin",
   "rel": "AUTHORED",
   "target": "synthetic:commit:e005"
  },
  {
   "source": "person:erin",
   "rel": "AUTHORED",
   "target": "synthetic:commit:e006"
  },
  {
   "source": "person:erin",
   "rel": "AUTHORED",
   "target": "synthetic:issue:14"
  },
  {
   "source": "person:erin",
   "rel": "AUTHORED",
   "target": "synthetic:pr:5"
  },
  {
   "source": "person:erin",
   "rel": "AUTHORED",
   "target": "synthetic:pr:6"
  },
  {
   "source": "person:erin",
   "rel": "AUTHORED",
   "target": "synthetic:pr:9"
  },
  {
   "source": "person:erin",
   "rel": "COMMENTED_ON",
   "target": "synthetic:pr:3"
  },
  {
   "source": "person:erin",
   "rel": "MEMBER_OF",
   "target": "team:payments"
  },
  {
   "source": "person:erin",
   "rel": "REVIEWED",
   "target": "synthetic:pr:3"
  },
  {
   "source": "person:erin",
   "rel": "REVIEWED",
   "target": "synthetic:pr:4"
  },
  {
   "source": "synthetic:commit:a001",
   "rel": "PART_OF",
   "target": "synthetic:pr:1"
  },
  {
   "source": "synthetic:commit:a001",
   "rel": "TOUCHES",
   "target": "system:Auth"
  },
  {
   "source": "synthetic:commit:a002",
   "rel": "PART_OF",
   "target": "synthetic:pr:1"
  },
  {
   "source": "synthetic:commit:a002",
   "rel": "TOUCHES",
   "target": "system:Auth"
  },
  {
   "source": "synthetic:commit:a003",
   "rel": "PART_OF",
   "target": "synthetic:pr:1"
  },
  {
   "source": "synthetic:commit:a003",
   "rel": "TOUCHES",
   "target": "system:Auth"
  },
  {
   "source": "synthetic:commit:a003",
   "rel": "TOUCHES",
   "target": "system:Web app"
  },
  {
   "source": "synthetic:commit:a004",
   "rel": "PART_OF",
   "target": "synthetic:pr:2"
  },
  {
   "source": "synthetic:commit:a004",
   "rel": "TOUCHES",
   "target": "system:Auth"
  },
  {
   "source": "synthetic:commit:a005",
   "rel": "PART_OF",
   "target": "synthetic:pr:2"
  },
  {
   "source": "synthetic:commit:a005",
   "rel": "TOUCHES",
   "target": "system:Auth"
  },
  {
   "source": "synthetic:commit:b001",
   "rel": "PART_OF",
   "target": "synthetic:pr:3"
  },
  {
   "source": "synthetic:commit:b001",
   "rel": "TOUCHES",
   "target": "system:Billing"
  },
  {
   "source": "synthetic:commit:b002",
   "rel": "PART_OF",
   "target": "synthetic:pr:3"
  },
  {
   "source": "synthetic:commit:b002",
   "rel": "TOUCHES",
   "target": "system:Billing"
  },
  {
   "source": "synthetic:commit:b002",
   "rel": "TOUCHES",
   "target": "system:Web app"
  },
  {
   "source": "synthetic:commit:b003",
   "rel": "PART_OF",
   "target": "synthetic:pr:3"
  },
  {
   "source": "synthetic:commit:b003",
   "rel": "TOUCHES",
   "target": "system:Billing"
  },
  {
   "source": "synthetic:commit:b004",
   "rel": "PART_OF",
   "target": "synthetic:pr:4"
  },
  {
   "source": "synthetic:commit:b004",
   "rel": "TOUCHES",
   "target": "system:Billing"
  },
  {
   "source": "synthetic:commit:b005",
   "rel": "PART_OF",
   "target": "synthetic:pr:4"
  },
  {
   "source": "synthetic:commit:b005",
   "rel": "TOUCHES",
   "target": "system:Billing"
  },
  {
   "source": "synthetic:commit:b005",
   "rel": "TOUCHES",
   "target": "system:Infra"
  },
  {
   "source": "synthetic:commit:c001",
   "rel": "PART_OF",
   "target": "synthetic:pr:10"
  },
  {
   "source": "synthetic:commit:c001",
   "rel": "TOUCHES",
   "target": "system:Auth"
  },
  {
   "source": "synthetic:commit:c002",
   "rel": "PART_OF",
   "target": "synthetic:pr:10"
  },
  {
   "source": "synthetic:commit:c002",
   "rel": "TOUCHES",
   "target": "system:Web app"
  },
  {
   "source": "synthetic:commit:d001",
   "rel": "PART_OF",
   "target": "synthetic:pr:7"
  },
  {
   "source": "synthetic:commit:d001",
   "rel": "TOUCHES",
   "target": "system:Infra"
  },
  {
   "source": "synthetic:commit:d002",
   "rel": "PART_OF",
   "target": "synthetic:pr:8"
  },
  {
   "source": "synthetic:commit:d002",
   "rel": "TOUCHES",
   "target": "system:Infra"
  },
  {
   "source": "synthetic:commit:e001",
   "rel": "PART_OF",
   "target": "synthetic:pr:5"
  },
  {
   "source": "synthetic:commit:e001",
   "rel": "TOUCHES",
   "target": "system:Web app"
  },
  {
   "source": "synthetic:commit:e002",
   "rel": "PART_OF",
   "target": "synthetic:pr:5"
  },
  {
   "source": "synthetic:commit:e002",
   "rel": "TOUCHES",
   "target": "system:Billing"
  },
  {
   "source": "synthetic:commit:e002",
   "rel": "TOUCHES",
   "target": "system:Web app"
  },
  {
   "source": "synthetic:commit:e003",
   "rel": "PART_OF",
   "target": "synthetic:pr:5"
  },
  {
   "source": "synthetic:commit:e003",
   "rel": "TOUCHES",
   "target": "system:Web app"
  },
  {
   "source": "synthetic:commit:e004",
   "rel": "PART_OF",
   "target": "synthetic:pr:6"
  },
  {
   "source": "synthetic:commit:e004",
   "rel": "TOUCHES",
   "target": "system:Web app"
  },
  {
   "source": "synthetic:commit:e005",
   "rel": "PART_OF",
   "target": "synthetic:pr:9"
  },
  {
   "source": "synthetic:commit:e005",
   "rel": "TOUCHES",
   "target": "system:Billing"
  },
  {
   "source": "synthetic:commit:e005",
   "rel": "TOUCHES",
   "target": "system:Web app"
  },
  {
   "source": "synthetic:commit:e006",
   "rel": "PART_OF",
   "target": "synthetic:pr:9"
  },
  {
   "source": "synthetic:commit:e006",
   "rel": "TOUCHES",
   "target": "system:Web app"
  },
  {
   "source": "synthetic:commit:z001",
   "rel": "TOUCHES",
   "target": "system:Infra"
  },
  {
   "source": "synthetic:commit:z002",
   "rel": "TOUCHES",
   "target": "system:Infra"
  },
  {
   "source": "synthetic:commit:z003",
   "rel": "TOUCHES",
   "target": "system:Infra"
  },
  {
   "source": "synthetic:commit:z004",
   "rel": "TOUCHES",
   "target": "system:Infra"
  },
  {
   "source": "synthetic:doc:docs/adr/001-managed-postgres.md",
   "rel": "MENTIONS",
   "target": "synthetic:pr:8"
  },
  {
   "source": "synthetic:doc:docs/adr/001-managed-postgres.md",
   "rel": "MENTIONS",
   "target": "system:Infra"
  },
  {
   "source": "synthetic:doc:docs/auth-design.md",
   "rel": "MENTIONS",
   "target": "synthetic:issue:11"
  },
  {
   "source": "synthetic:doc:docs/auth-design.md",
   "rel": "MENTIONS",
   "target": "synthetic:pr:1"
  },
  {
   "source": "synthetic:doc:docs/auth-design.md",
   "rel": "MENTIONS",
   "target": "system:Auth"
  },
  {
   "source": "synthetic:doc:docs/billing-runbook.md",
   "rel": "MENTIONS",
   "target": "synthetic:pr:4"
  },
  {
   "source": "synthetic:doc:docs/billing-runbook.md",
   "rel": "MENTIONS",
   "target": "system:Billing"
  },
  {
   "source": "synthetic:pr:1",
   "rel": "CLOSES",
   "target": "synthetic:issue:11"
  },
  {
   "source": "synthetic:pr:3",
   "rel": "CLOSES",
   "target": "synthetic:issue:12"
  },
  {
   "source": "synthetic:pr:5",
   "rel": "CLOSES",
   "target": "synthetic:issue:13"
  },
  {
   "source": "synthetic:pr:6",
   "rel": "MENTIONS",
   "target": "synthetic:pr:1"
  },
  {
   "source": "synthetic:pr:9",
   "rel": "MENTIONS",
   "target": "synthetic:pr:3"
  },
  {
   "source": "team:identity",
   "rel": "OWNS",
   "target": "system:Auth"
  },
  {
   "source": "team:identity",
   "rel": "OWNS",
   "target": "system:Web app"
  },
  {
   "source": "team:payments",
   "rel": "OWNS",
   "target": "system:Billing"
  }
 ],
 "territories": [
  {
   "id": "system:Billing",
   "name": "Billing",
   "system_uid": "system:Billing",
   "size": 16,
   "systems": 1
  },
  {
   "id": "system:Auth",
   "name": "Auth",
   "system_uid": "system:Auth",
   "size": 15,
   "systems": 1
  },
  {
   "id": "system:Infra",
   "name": "Infra",
   "system_uid": "system:Infra",
   "size": 12,
   "systems": 1
  },
  {
   "id": "system:Web app",
   "name": "Web app",
   "system_uid": "system:Web app",
   "size": 9,
   "systems": 1
  },
  {
   "id": "none",
   "name": "Not linked to code",
   "system_uid": null,
   "size": 3,
   "systems": 0
  }
 ],
 "bots": 1,
 "bots_shown": true,
 "comments": 7
};
