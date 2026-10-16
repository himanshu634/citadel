/**
 * Sample data taken from apps/backend/examples/synthetic_company, so the dashboard opens in a
 * realistic state before the backend API exists. Replace with API calls; keep the shapes.
 */
import type { CitedAnswer, GraphCount, Person, SystemActivity, WorkItem } from '$lib/types';

export const company = { slug: 'synthetic', name: 'Synthetic Co', since: '2026-01-01' };
export const companies = [company, { slug: 'falkordb', name: 'FalkorDB', since: '2025-10-01' }];

export const graphCounts: GraphCount[] = [
	{ type: 'person', count: 5 },
	{ type: 'team', count: 2 },
	{ type: 'system', count: 4 },
	{ type: 'work-item', count: 15 },
	{ type: 'change', count: 25 },
	{ type: 'document', count: 3 }
];

export const lastSync = '2026-10-16 09:12';

export const featuredAnswer: CitedAnswer = {
	question: 'Why did we replace sessions with JWTs?',
	parts: [
		{
			text: 'Alice replaced server-side sessions with short-lived JWTs because the session table was the main source of database load',
			cite: [1, 2]
		},
		{ text: '. Refresh tokens stay server-side', cite: [3] },
		{ text: '.' }
	],
	path: [
		{ node: { uid: 'person:alice', type: 'person', label: 'alice' }, edge: 'AUTHORED' },
		{ node: { uid: 'synthetic:pr:1', type: 'work-item', label: 'PR #1' }, edge: 'CLOSES' },
		{ node: { uid: 'synthetic:issue:11', type: 'work-item', label: 'Issue #11' }, edge: 'TOUCHES' },
		{ node: { uid: 'system:Auth', type: 'system', label: 'Auth' } }
	],
	sources: [
		{
			uid: 'synthetic:pr:1',
			title: 'feat(auth): switch sessions to JWT',
			meta: 'PR #1, merged 6 Feb by alice',
			url: 'https://example.com/synthetic/app/pull/1'
		},
		{
			uid: 'synthetic:issue:11',
			title: 'Session table causes DB load spikes',
			meta: 'Issue #11, closed 6 Feb'
		},
		{
			uid: 'synthetic:doc:docs/auth-design.md',
			title: 'Auth design',
			meta: 'docs/auth-design.md'
		}
	]
};

export const recentWork: WorkItem[] = [
	{ uid: 'synthetic:issue:14', kind: 'issue', number: 14, title: 'Invoice emails sometimes sent twice', state: 'open', author: 'erin', date: '2026-09-10', system: 'Billing' },
	{ uid: 'synthetic:pr:10', kind: 'pull_request', number: 10, title: 'refactor(auth): extract token service', state: 'merged', author: 'carol', date: '2026-09-01', system: 'Auth' },
	{ uid: 'synthetic:pr:9', kind: 'pull_request', number: 9, title: 'feat(billing): usage-based add-ons', state: 'open', author: 'erin', date: '2026-08-20', system: 'Billing' },
	{ uid: 'synthetic:slack:thread:eng-2026-07-15', kind: 'thread', title: '#eng: should billing own the checkout page?', state: 'open', author: 'bob', date: '2026-07-15' },
	{ uid: 'synthetic:pr:8', kind: 'pull_request', number: 8, title: 'build(infra): move to managed Postgres', state: 'merged', author: 'dave', date: '2026-07-01', system: 'Infra' },
	{ uid: 'synthetic:pr:6', kind: 'pull_request', number: 6, title: 'fix(web): login redirect loop', state: 'merged', author: 'erin', date: '2026-06-01', system: 'Web app' }
];

export const people: Person[] = [
	{ login: 'alice', name: 'Alice Kim', team: 'identity', prs: 2, reviews: 3 },
	{ login: 'bob', name: 'Bob Ortiz', team: 'payments', prs: 2, reviews: 2 },
	{ login: 'carol', name: 'Carol Singh', team: 'identity', prs: 1, reviews: 3 },
	{ login: 'dave', name: 'Dave Mensah', team: 'payments', prs: 2, reviews: 2 },
	{ login: 'erin', name: 'Erin Novak', team: 'identity', prs: 3, reviews: 2 }
];

export const systemActivity: SystemActivity[] = [
	{ name: 'Auth', team: 'identity', changes: 9 },
	{ name: 'Billing', team: 'payments', changes: 8 },
	{ name: 'Web app', team: 'identity', changes: 5 },
	{ name: 'Infra', team: 'unowned', changes: 3 }
];

export const suggestedQuestions = [
	'Who should review a change to billing?',
	'What broke checkout on mobile?',
	'Which decisions are recorded as ADRs?'
];
