// Example walks for the gallery: the synthetic company's "Who does Alice work with?" (real rows).
import type { AskAnswer, WalkNode, WalkStep } from '$lib/types';

const person = (login: string): WalkNode => ({ uid: `person:${login}`, label: 'Person', title: login, url: null });
const pr = (n: number, title: string): WalkNode => ({
	uid: `synthetic:pr:${n}`,
	label: 'WorkItem',
	title: `#${n} ${title}`,
	url: `https://example.com/synthetic/app/pull/${n}`
});
const identity: WalkNode = { uid: 'team:identity', label: 'Team', title: 'identity', url: null };
const auth: WalkNode = { uid: 'system:Auth', label: 'System', title: 'Auth', url: null };
const web: WalkNode = { uid: 'system:Web app', label: 'System', title: 'Web app', url: null };
const pr10 = pr(10, 'refactor(auth): extract token service');
const pr1 = pr(1, 'feat(auth): switch sessions to JWT');

const profile: WalkStep = {
	id: 's1',
	n: 1,
	tool: 'person_profile',
	input: { login: 'alice' },
	status: 'done',
	ms: 12,
	count: 1,
	error: null,
	rows: [{ login: 'alice', person_uid: 'person:alice', prs_authored: 2, reviews_given: 3 }],
	nodes: [person('alice'), identity, auth, web],
	rels: [
		{ from: 'person:alice', to: identity.uid, type: 'MEMBER_OF', inferred: false },
		{ from: 'person:alice', to: auth.uid, type: 'works on', inferred: true, note: '5 changes' },
		{ from: 'person:alice', to: web.uid, type: 'works on', inferred: true, note: '1 change' }
	]
};

const experts: WalkStep = {
	id: 's2',
	n: 2,
	tool: 'experts_for_system',
	input: { system: 'Auth' },
	status: 'done',
	ms: 11,
	count: 3,
	error: null,
	rows: [
		{ login: 'alice', person_uid: 'person:alice', score: 1.16, changes: 5, reviews: 1, system_uid: auth.uid },
		{ login: 'carol', person_uid: 'person:carol', score: 0.877, changes: 1, reviews: 2, system_uid: auth.uid },
		{ login: 'dave', person_uid: 'person:dave', score: 0.071, changes: 0, reviews: 1, system_uid: auth.uid }
	],
	nodes: [auth, person('alice'), person('carol'), person('dave'), identity],
	rels: [
		{ from: 'person:carol', to: auth.uid, type: 'works on', inferred: true, note: 'score 0.88' },
		{ from: 'person:dave', to: auth.uid, type: 'works on', inferred: true, note: 'score 0.07' },
		{ from: 'person:carol', to: identity.uid, type: 'MEMBER_OF', inferred: false }
	]
};

const paths: WalkStep = {
	id: 's3',
	n: 3,
	tool: 'path_between',
	input: { from_uid: 'person:alice', to_uid: 'person:carol' },
	status: 'done',
	ms: 9,
	count: 2,
	error: null,
	rows: [
		{
			length: 2,
			nodes: [
				{ uid: 'person:alice', name: 'alice' },
				{ uid: pr10.uid, name: 'refactor(auth): extract token service' },
				{ uid: 'person:carol', name: 'carol' }
			],
			rels: [
				{ type: 'REVIEWED', from: 'person:alice', to: pr10.uid },
				{ type: 'AUTHORED', from: 'person:carol', to: pr10.uid }
			]
		},
		{
			length: 2,
			nodes: [
				{ uid: 'person:alice', name: 'alice' },
				{ uid: pr1.uid, name: 'feat(auth): switch sessions to JWT' },
				{ uid: 'person:carol', name: 'carol' }
			],
			rels: [
				{ type: 'COMMENTED_ON', from: 'person:alice', to: pr1.uid },
				{ type: 'REVIEWED', from: 'person:carol', to: pr1.uid }
			]
		}
	],
	nodes: [person('alice'), pr10, person('carol'), pr1],
	rels: [
		{ from: 'person:alice', to: pr10.uid, type: 'REVIEWED', inferred: false },
		{ from: 'person:carol', to: pr10.uid, type: 'AUTHORED', inferred: false },
		{ from: 'person:alice', to: pr1.uid, type: 'COMMENTED_ON', inferred: false },
		{ from: 'person:carol', to: pr1.uid, type: 'REVIEWED', inferred: false }
	]
};

const check: WalkStep = { id: 's9', n: null, tool: 'submit_answer', input: {}, status: 'done', error: null };

/** Step 2 asked for, step 1 done: the walk while the answer is running. */
export const running: WalkStep[] = [profile, { ...experts, status: 'running', ms: null, count: null, rows: [], nodes: [], rels: [] }];

/** All steps done and the answer checked. */
export const done: WalkStep[] = [profile, experts, paths, check];

export const answer: AskAnswer = {
	thread_id: 'gallery',
	text: 'Carol Singh. Alice approved carol\'s **token-service refactor** [1], carol reviewed Alice\'s switch to JWT [2], and both are in team `identity` [3].\n\n- On Auth they rank first and second by recent work [4].',
	sources: [
		{ uid: pr10.uid, title: 'refactor(auth): extract token service', url: pr10.url, label: 'WorkItem', step: 3 },
		{ uid: pr1.uid, title: 'feat(auth): switch sessions to JWT', url: pr1.url, label: 'WorkItem', step: 3 },
		{ uid: identity.uid, title: 'identity', url: null, label: 'Team', step: 1 },
		{ uid: auth.uid, title: 'Auth', url: null, label: 'System', step: 1 }
	],
	path: [],
	stop: 'tool_use',
	model: 'claude-haiku-5-5'
};

/** A failed call, a call that found nothing, and a rejected answer check. */
export const rough: WalkStep[] = [
	{ id: 'e1', n: 1, tool: 'path_between', input: { from_uid: 'person:alice' }, status: 'done', ms: 2, count: 0, error: 'invalid input for path_between: to_uid is required', rows: [], nodes: [], rels: [] },
	{ id: 'e2', n: 2, tool: 'path_between', input: { from_uid: 'person:alice', to_uid: 'person:bob', max_len: 2 }, status: 'done', ms: 41, count: 0, error: null, rows: [], nodes: [], rels: [] },
	{ id: 'e3', n: null, tool: 'submit_answer', input: {}, status: 'done', error: 'These uids did not appear in any tool result: person:zed.' }
];

/** An answer that also cites a tool on an outside MCP server (no node in the walk). */
export const withMcp: AskAnswer = {
	...answer,
	text: 'Carol and Alice pair on token work [1], as the handbook notes [2].',
	sources: [
		answer.sources[0],
		{ uid: 'mcp:handbook/search_handbook', title: 'search_handbook on handbook', url: null, label: 'MCP', step: null }
	]
};

export const stopped: AskAnswer = { ...answer, text: null, sources: [], stop: 'stopped' };
export const refused: AskAnswer = { ...answer, text: null, sources: [], stop: 'refusal' };
