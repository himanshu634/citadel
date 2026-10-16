import { describe, expect, test } from 'vitest';
import type { WalkStep } from './types';
import {
	STAGE,
	answerBlocks,
	highlightFor,
	layoutWalk,
	mergeWalk,
	nodeType,
	relKey,
	rowViews,
	shortUid,
	stepCall,
	stepSentence
} from './walk';

const person = (login: string) => ({ uid: `person:${login}`, label: 'Person', title: login, url: null });
const pr10 = { uid: 'synthetic:pr:10', label: 'WorkItem', title: '#10 refactor(auth)', url: 'u10' };
const pr1 = { uid: 'synthetic:pr:1', label: 'WorkItem', title: '#1 feat(auth): JWT', url: 'u1' };
const identity = { uid: 'team:identity', label: 'Team', title: 'identity', url: null };
const auth = { uid: 'system:Auth', label: 'System', title: 'Auth', url: null };

const profile: WalkStep = {
	id: 't1',
	n: 1,
	tool: 'person_profile',
	input: { login: 'alice' },
	status: 'done',
	nodes: [person('alice'), identity, auth],
	rels: [
		{ from: 'person:alice', to: 'team:identity', type: 'MEMBER_OF', inferred: false },
		{ from: 'person:alice', to: 'system:Auth', type: 'works on', inferred: true }
	],
	rows: [{ login: 'alice', person_uid: 'person:alice', prs_authored: 2 }]
};

const paths: WalkStep = {
	id: 't3',
	n: 2,
	tool: 'path_between',
	input: { from_uid: 'person:alice', to_uid: 'person:carol' },
	status: 'done',
	nodes: [person('alice'), pr10, person('carol'), pr1, identity],
	rels: [
		{ from: 'person:alice', to: pr10.uid, type: 'REVIEWED', inferred: false },
		{ from: 'person:carol', to: pr10.uid, type: 'AUTHORED', inferred: false },
		{ from: 'person:alice', to: pr1.uid, type: 'COMMENTED_ON', inferred: false },
		{ from: 'person:carol', to: pr1.uid, type: 'REVIEWED', inferred: false },
		{ from: 'person:alice', to: 'team:identity', type: 'MEMBER_OF', inferred: false },
		{ from: 'person:carol', to: 'team:identity', type: 'MEMBER_OF', inferred: false }
	],
	rows: [
		{
			nodes: [{ uid: 'person:alice', name: 'alice' }, { uid: pr10.uid, name: 'refactor(auth)' }, { uid: 'person:carol', name: 'carol' }],
			rels: [
				{ type: 'REVIEWED', from: 'person:alice', to: pr10.uid },
				{ type: 'AUTHORED', from: 'person:carol', to: pr10.uid }
			]
		},
		{
			nodes: [{ uid: 'person:alice', name: 'alice' }, { uid: 'team:identity', name: 'identity' }, { uid: 'person:carol', name: 'carol' }],
			rels: [
				{ type: 'MEMBER_OF', from: 'person:alice', to: 'team:identity' },
				{ type: 'MEMBER_OF', from: 'person:carol', to: 'team:identity' }
			]
		}
	]
};

const check: WalkStep = { id: 't9', n: null, tool: 'submit_answer', input: {}, status: 'done', error: null };

describe('mergeWalk', () => {
	test('keeps each node and link once, with the step that first touched it', () => {
		const walk = mergeWalk([profile, paths, check]);
		expect(walk.focus).toBe('person:alice');
		const step = Object.fromEntries(walk.nodes.map((n) => [n.uid, n.step]));
		expect(step).toEqual({
			'person:alice': 1,
			'team:identity': 1,
			'system:Auth': 1,
			'synthetic:pr:10': 2,
			'person:carol': 2,
			'synthetic:pr:1': 2
		});
		const memberOf = walk.rels.filter((r) => r.type === 'MEMBER_OF');
		expect(memberOf.map((r) => [r.from, r.step])).toEqual([
			['person:alice', 1],
			['person:carol', 2]
		]);
	});

	test('a running step adds nothing yet', () => {
		const running: WalkStep = { id: 't4', n: 3, tool: 'work_history', input: {}, status: 'running' };
		expect(mergeWalk([profile, running]).nodes).toHaveLength(3);
	});
});

describe('layoutWalk', () => {
	const walk = mergeWalk([profile, paths]);

	test('puts the start in the middle and every node on stage, the same way each time', () => {
		const pos = layoutWalk(walk);
		expect(pos.get('person:alice')).toEqual({ x: STAGE.width / 2, y: STAGE.height / 2 });
		for (const p of pos.values()) {
			expect(p.x).toBeGreaterThanOrEqual(0);
			expect(p.x).toBeLessThanOrEqual(STAGE.width);
			expect(p.y).toBeGreaterThanOrEqual(0);
			expect(p.y).toBeLessThanOrEqual(STAGE.height);
		}
		expect(layoutWalk(walk)).toEqual(pos);
	});

	test('nodes do not sit on top of each other', () => {
		const pos = [...layoutWalk(walk).values()];
		for (let i = 0; i < pos.length; i++)
			for (let j = i + 1; j < pos.length; j++) {
				const far = Math.abs(pos[i].x - pos[j].x) > 60 || Math.abs(pos[i].y - pos[j].y) > 24;
				expect(far).toBe(true);
			}
	});

	test('a new step barely moves the nodes already drawn', () => {
		const first = layoutWalk(mergeWalk([profile]));
		const next = layoutWalk(walk, first);
		for (const [uid, p] of first) {
			const q = next.get(uid)!;
			expect(Math.hypot(p.x - q.x, p.y - q.y)).toBeLessThan(80);
		}
	});
});

describe('highlightFor', () => {
	const steps = [profile, paths, check];

	test('a node found by path_between lights the paths through it', () => {
		const h = highlightFor({ uid: pr10.uid, step: 2 }, steps);
		expect([...h.nodes].sort()).toEqual(['person:alice', 'person:carol', pr10.uid].sort());
		expect(h.rels).toEqual(
			new Set([
				relKey({ from: 'person:alice', to: pr10.uid, type: 'REVIEWED' }),
				relKey({ from: 'person:carol', to: pr10.uid, type: 'AUTHORED' })
			])
		);
	});

	test('a hub lights only its links in the step that found it, not the whole graph', () => {
		const h = highlightFor({ uid: 'team:identity', step: 1 }, steps);
		expect([...h.nodes].sort()).toEqual(['person:alice', 'team:identity']);
		expect(h.rels.size).toBe(1);
	});

	test('a later step about the cited node adds its links: found in step 1, author from step 3', () => {
		const opened: WalkStep = {
			id: 't5',
			n: 3,
			tool: 'get_entity',
			input: { uid: pr10.uid },
			status: 'done',
			nodes: [pr10, person('carol'), auth],
			rels: [
				{ from: 'person:carol', to: pr10.uid, type: 'AUTHORED', inferred: false },
				{ from: pr10.uid, to: 'system:Auth', type: 'TOUCHES', inferred: false }
			]
		};
		const found: WalkStep = {
			...profile,
			nodes: [...profile.nodes!, pr10],
			rels: [...profile.rels!, { from: 'person:alice', to: pr10.uid, type: 'REVIEWED', inferred: false }]
		};
		const h = highlightFor({ uid: pr10.uid, step: 1 }, [found, opened]);
		expect(h.rels).toEqual(
			new Set([
				relKey({ from: 'person:alice', to: pr10.uid, type: 'REVIEWED' }),
				relKey({ from: 'person:carol', to: pr10.uid, type: 'AUTHORED' }),
				relKey({ from: pr10.uid, to: 'system:Auth', type: 'TOUCHES' })
			])
		);
		expect(h.nodes.has('person:carol')).toBe(true);
	});

	test('a uid no step returned lights only itself', () => {
		const h = highlightFor({ uid: 'person:zed', step: null }, steps);
		expect([...h.nodes]).toEqual(['person:zed']);
		expect(h.rels.size).toBe(0);
	});
});

describe('words', () => {
	test('uids, sentences and calls read like people write them', () => {
		expect(shortUid('person:alice')).toBe('alice');
		expect(shortUid('synthetic:pr:10')).toBe('PR #10');
		expect(shortUid('synthetic:commit:b002')).toBe('commit b002');
		expect(shortUid('system:Web app')).toBe('Web app');
		expect(stepSentence(paths)).toBe('Finding how alice and carol connect');
		expect(stepSentence({ tool: 'experts_for_system', input: { system: 'Auth' } })).toBe(
			'Asking who knows Auth best'
		);
		expect(stepSentence({ tool: 'mystery', input: {} })).toBe('Running mystery');
		expect(stepCall(paths)).toBe('path_between(alice → carol)');
		expect(stepCall({ tool: 'experts_for_system', input: { system: 'Auth', limit: 5 } })).toBe(
			'experts_for_system(system: "Auth", limit: 5)'
		);
	});

	test('nodeType maps graph labels and falls back to grey', () => {
		expect(nodeType('WorkItem')).toBe('work-item');
		expect(nodeType('Strange')).toBe('document');
		expect(nodeType(null)).toBe('document');
	});
});

describe('rowViews', () => {
	test('a path row is a chain with arrows the way each link points', () => {
		const [first] = rowViews(paths);
		expect(first.chain).toEqual([
			{ title: 'alice', uid: 'person:alice', rel: 'REVIEWED', forward: true },
			{ title: 'refactor(auth)', uid: pr10.uid, rel: 'AUTHORED', forward: false },
			{ title: 'carol', uid: 'person:carol' }
		]);
	});

	test('other rows are one line with their name and numbers, and the uids they name', () => {
		const rows = rowViews({
			tool: 'experts_for_system',
			rows: [{ login: 'carol', person_uid: 'person:carol', score: 0.877, changes: 1, reviews: 2, system_uid: 'system:Auth' }]
		});
		expect(rows[0].text).toBe('carol · score 0.88 · changes 1 · reviews 2');
		expect(rows[0].uids).toEqual(['person:carol', 'system:Auth']);
		const pr = rowViews({ tool: 'work_history', rows: [{ uid: 'x:pr:3', number: 3, title: 'feat: y' }] });
		expect(pr[0].text).toBe('#3 feat: y');
	});
});

describe('answerBlocks', () => {
	test('paragraphs, lists, bold, code and citations; never HTML', () => {
		const text =
			"Carol **Singh** is on `identity` [1][2].\nSecond line.\n\n- Reviewed #10 [3, 4]\n- <b>not html</b>\n\n1. one\n2. two";
		expect(answerBlocks(text)).toEqual([
			{
				kind: 'p',
				inlines: [
					{ kind: 'text', text: 'Carol ' },
					{ kind: 'bold', text: 'Singh' },
					{ kind: 'text', text: ' is on ' },
					{ kind: 'code', text: 'identity' },
					{ kind: 'text', text: ' ' },
					{ kind: 'cite', n: 1 },
					{ kind: 'cite', n: 2 },
					{ kind: 'text', text: '. Second line.' }
				]
			},
			{
				kind: 'ul',
				items: [
					[
						{ kind: 'text', text: 'Reviewed #10 ' },
						{ kind: 'cite', n: 3 },
						{ kind: 'cite', n: 4 }
					],
					[{ kind: 'text', text: '<b>not html</b>' }]
				]
			},
			{ kind: 'ol', items: [[{ kind: 'text', text: 'one' }], [{ kind: 'text', text: 'two' }]] }
		]);
	});
});
