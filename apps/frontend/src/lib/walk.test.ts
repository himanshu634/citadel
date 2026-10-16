import { describe, expect, test } from 'vitest';
import type { WalkStep } from './types';
import {
	CARRY_MAX,
	STAGE,
	answerBlocks,
	answerPlainText,
	carryOver,
	highlightFor,
	ledgerItems,
	layoutWalk,
	mergeWalk,
	nodeType,
	relKey,
	rowViews,
	shortUid,
	stepCall,
	stepHighlight,
	stepSentence,
	stepState
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

describe('answerPlainText', () => {
	test('takes out a citation and the space before it', () => {
		expect(answerPlainText('Carol is on identity [1].')).toBe('Carol is on identity.');
	});

	test('takes out a citation with several numbers', () => {
		expect(answerPlainText('Reviewed #10 [1, 2] and shipped.')).toBe('Reviewed #10 and shipped.');
		expect(answerPlainText('Reviewed #10 [1,2 , 3].')).toBe('Reviewed #10.');
	});

	test('takes out every marker, also ones that touch', () => {
		expect(answerPlainText('Alice [1] reviewed it [2][3], Bob [4, 5] wrote it.')).toBe('Alice reviewed it, Bob wrote it.');
	});

	test('leaves text without markers as it was, Markdown and line breaks included', () => {
		const text = 'Carol **Singh** is on `identity`.\n\n- one\n- two [x] and [1a] and []';
		expect(answerPlainText(text)).toBe(text);
		expect(answerPlainText('')).toBe('');
	});

	test('changes nothing but the markers', () => {
		expect(answerPlainText('A **bold** claim [1].\n- item [2, 3]\n- next')).toBe('A **bold** claim.\n- item\n- next');
	});
});

// --- the ledger -----------------------------------------------------------------------------

const call = (n: number, tool: string, input: Record<string, unknown>, extra: Partial<WalkStep> = {}): WalkStep => ({
	id: `c${n}`,
	n,
	tool,
	input,
	status: 'done',
	count: 3,
	ms: 10,
	...extra
});
const history = (n: number, system: string, extra: Partial<WalkStep> = {}) => call(n, 'work_history', { system }, extra);

describe('stepSentence', () => {
	test('reads in the present while it runs and in the past once done', () => {
		const step = { tool: 'work_history', input: { system: 'Auth' } };
		expect(stepSentence(step)).toBe('Reading recent work on Auth');
		expect(stepSentence(step, true)).toBe('Read recent work on Auth');
		expect(stepSentence(paths, true)).toBe('Found how alice and carol connect');
	});

	test('a tool it does not know is named as it is', () => {
		expect(stepSentence({ tool: 'mystery', input: {} })).toBe('Running mystery');
		expect(stepSentence({ tool: 'mystery', input: {} }, true)).toBe('Ran mystery');
	});
});

describe('stepState', () => {
	test('a running step is running, whatever else it holds', () => {
		expect(stepState(history(1, 'Auth', { status: 'running', count: undefined }))).toBe('running');
	});

	test('a step that returned rows is done', () => {
		expect(stepState(history(1, 'Auth'))).toBe('done');
	});

	test('a step with no rows is empty, and an unknown count is not', () => {
		expect(stepState(history(1, 'Auth', { count: 0 }))).toBe('empty');
		expect(stepState(history(1, 'Auth', { count: undefined }))).toBe('done');
	});

	test('a step with an error failed', () => {
		expect(stepState(history(1, 'Auth', { error: 'boom', count: 0 }))).toBe('failed');
	});

	test('an error that starts with "Not run" means it never ran', () => {
		expect(stepState(history(1, 'Auth', { error: 'Not run: step limit reached' }))).toBe('not-run');
		expect(stepState(history(1, 'Auth', { error: 'Could not run' }))).toBe('failed');
	});
});

describe('ledgerItems', () => {
	const four = [history(1, 'Web app'), history(2, 'Billing'), history(3, 'Infra'), history(4, 'Auth')];

	test('while the answer runs, each graph step is its own row and the answer check is left out', () => {
		const items = ledgerItems([...four, check], false);
		expect(items).toHaveLength(4);
		expect(items.map((i) => i.steps.length)).toEqual([1, 1, 1, 1]);
		expect(items[0].sentence).toBe('Read recent work on Web app');
		expect(items.every((i) => i.state === 'done')).toBe(true);
	});

	test('a step still running reads in the present', () => {
		const [item] = ledgerItems([history(1, 'Auth', { status: 'running', count: undefined, ms: undefined })], false);
		expect(item.sentence).toBe('Reading recent work on Auth');
		expect(item.state).toBe('running');
		expect(item.count).toBeNull();
		expect(item.ms).toBeNull();
	});

	test('once settled, a run of the same tool folds into one row with summed count and time', () => {
		const items = ledgerItems([...four.map((s, i) => ({ ...s, count: i + 1, ms: 100 * (i + 1) })), check], true);
		expect(items).toHaveLength(1);
		expect(items[0].sentence).toBe('Read recent work on 4 systems: Web app, Billing, Infra, Auth');
		expect(items[0].steps.map((s) => s.n)).toEqual([1, 2, 3, 4]);
		expect(items[0].state).toBe('done');
		expect(items[0].count).toBe(10);
		expect(items[0].ms).toBe(1000);
	});

	test('a count or time that no step reported stays unknown', () => {
		const bare = four.map((s) => ({ ...s, count: undefined, ms: undefined }));
		const [item] = ledgerItems(bare, true);
		expect(item.count).toBeNull();
		expect(item.ms).toBeNull();
	});

	test('a single step is not folded', () => {
		const items = ledgerItems([history(1, 'Auth'), check], true);
		expect(items).toHaveLength(1);
		expect(items[0].steps).toHaveLength(1);
		expect(items[0].sentence).toBe('Read recent work on Auth');
	});

	test('an empty step in the middle breaks the run and keeps its own row', () => {
		const items = ledgerItems(
			[history(1, 'Web app'), history(2, 'Billing'), history(3, 'Infra', { count: 0 }), history(4, 'Auth'), history(5, 'Data')],
			true
		);
		expect(items.map((i) => i.steps.map((s) => s.n))).toEqual([[1, 2], [3], [4, 5]]);
		expect(items[0].sentence).toBe('Read recent work on 2 systems: Web app, Billing');
		expect(items[1].state).toBe('empty');
		expect(items[1].sentence).toBe('Read recent work on Infra');
		expect(items[2].sentence).toBe('Read recent work on 2 systems: Auth, Data');
	});

	test('a failed step in the middle keeps its own row too', () => {
		const items = ledgerItems([history(1, 'Web app'), history(2, 'Billing', { error: 'boom' }), history(3, 'Auth')], true);
		expect(items.map((i) => [i.steps.length, i.state])).toEqual([
			[1, 'done'],
			[1, 'failed'],
			[1, 'done']
		]);
	});

	test('different tools are not folded together', () => {
		const items = ledgerItems([history(1, 'Auth'), call(2, 'experts_for_system', { system: 'Auth' }), history(3, 'Billing')], true);
		expect(items.map((i) => i.steps.map((s) => s.n))).toEqual([[1], [2], [3]]);
	});

	test('a tool with no repeat wording says how many more there were', () => {
		const items = ledgerItems([call(1, 'list_systems', {}), call(2, 'list_systems', {})], true);
		expect(items).toHaveLength(1);
		expect(items[0].sentence).toBe('Listed the systems, and 1 more like it');
	});
});

describe('stepHighlight', () => {
	test('lights the nodes and links the step added', () => {
		const h = stepHighlight(profile);
		expect(h.nodes).toEqual(new Set(['person:alice', 'team:identity', 'system:Auth']));
		expect(h.rels).toEqual(
			new Set([
				relKey({ from: 'person:alice', to: 'team:identity', type: 'MEMBER_OF' }),
				relKey({ from: 'person:alice', to: 'system:Auth', type: 'works on' })
			])
		);
	});

	test('a step that touched nothing lights nothing', () => {
		const h = stepHighlight(check);
		expect(h.nodes.size).toBe(0);
		expect(h.rels.size).toBe(0);
	});
});

describe('carryOver', () => {
	const rel = (from: string, to: string, type = 'WORKS_ON') => ({ from, to, type, inferred: false });
	const node = (uid: string) => ({ uid, label: 'System', title: uid.split(':')[1], url: null });
	const stepWith = (n: number, nodes: ReturnType<typeof node>[], rels: ReturnType<typeof rel>[]): WalkStep =>
		call(n, 'get_entity', { uid: nodes[0].uid }, { nodes, rels });

	test('brings a node an earlier question found when it links to a node of this answer', () => {
		const earlier = [stepWith(1, [node('person:alice'), node('system:Auth')], [rel('person:alice', 'system:Auth')])];
		const now = [stepWith(1, [node('system:Auth')], [])];
		const carried = carryOver(earlier, now);
		expect(carried.nodes.map((n) => n.uid)).toEqual(['person:alice']);
		expect(carried.rels).toEqual([rel('person:alice', 'system:Auth')]);
	});

	test('carries the node as plain graph data, without the walk bookkeeping', () => {
		const earlier = [stepWith(1, [node('person:alice'), node('system:Auth')], [rel('person:alice', 'system:Auth')])];
		const carried = carryOver(earlier, [stepWith(1, [node('system:Auth')], [])]);
		expect(carried.nodes[0]).toEqual(node('person:alice'));
		expect(carried.rels[0]).toEqual(rel('person:alice', 'system:Auth'));
	});

	test('a link with both ends in this answer is not carried, nor is one with neither', () => {
		const earlier = [
			stepWith(1, [node('person:alice'), node('system:Auth'), node('person:bob'), node('system:Billing')], [
				rel('person:alice', 'system:Auth'),
				rel('person:bob', 'system:Billing')
			])
		];
		const now = [stepWith(1, [node('person:alice'), node('system:Auth')], [])];
		expect(carryOver(earlier, now)).toEqual({ nodes: [], rels: [] });
	});

	test('a link this answer already drew is not carried again', () => {
		const same = rel('person:alice', 'system:Auth');
		const earlier = [stepWith(1, [node('person:alice'), node('system:Auth')], [same])];
		const now = [stepWith(1, [node('system:Auth')], [same])];
		expect(carryOver(earlier, now)).toEqual({ nodes: [], rels: [] });
	});

	test('carries nothing while this answer has no nodes yet', () => {
		const earlier = [stepWith(1, [node('person:alice'), node('system:Auth')], [rel('person:alice', 'system:Auth')])];
		expect(carryOver(earlier, [])).toEqual({ nodes: [], rels: [] });
		expect(carryOver(earlier, [history(1, 'Auth', { status: 'running' }), check])).toEqual({ nodes: [], rels: [] });
	});

	test('carries at most CARRY_MAX nodes, and only the links to those nodes', () => {
		const people = Array.from({ length: CARRY_MAX + 3 }, (_, i) => node(`person:p${i}`));
		const earlier = [stepWith(1, [node('system:Auth'), ...people], people.map((p) => rel(p.uid, 'system:Auth')))];
		const now = [stepWith(1, [node('system:Auth')], [])];
		const carried = carryOver(earlier, now);
		expect(carried.nodes).toHaveLength(CARRY_MAX);
		expect(carried.rels).toHaveLength(CARRY_MAX);
		const kept = new Set(carried.nodes.map((n) => n.uid));
		expect(carried.rels.every((r) => kept.has(r.from))).toBe(true);
		expect(carryOver(earlier, now, 2).nodes).toHaveLength(2);
	});

	test('several links to one carried node count it once', () => {
		const earlier = [
			stepWith(1, [node('person:alice'), node('system:Auth'), node('system:Billing')], [
				rel('person:alice', 'system:Auth'),
				rel('person:alice', 'system:Billing', 'REVIEWED')
			])
		];
		const now = [stepWith(1, [node('system:Auth'), node('system:Billing')], [])];
		const carried = carryOver(earlier, now, 1);
		expect(carried.nodes.map((n) => n.uid)).toEqual(['person:alice']);
		expect(carried.rels).toHaveLength(2);
	});
});
