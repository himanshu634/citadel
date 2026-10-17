import { describe, expect, it } from 'vitest';
import { actorName, anchorOf, doingNow, featured, shownRun, stepLine, stepsSummary, trailOf } from './activity';
import type { ActivityRun, ActivityStep } from './types';

function step(n: number, tool: string, input: Record<string, unknown>, touched: string[], extra: Partial<ActivityStep> = {}): ActivityStep {
	return { n, actor: 'brain', tool, kind: 'graph', input, status: 'done', count: touched.length, error: null, touched, ...extra };
}

function run(steps: ActivityStep[], status: ActivityRun['status'] = 'done', id = 'ask:t:1'): ActivityRun {
	return { id, source: 'ask', actor: 'brain', title: 'Who owns Auth?', status, started_at: '2026-10-17T09:00:00Z', ended_at: null, thread_id: 't', steps };
}

/** Where the test map draws a node: systems and their work by name, chunks nowhere. */
const drawn = (uid: string): string | null => {
	if (uid.startsWith('chunk:')) return null;
	if (uid === 'system:Billing' || uid === 'pr:9') return 'billing';
	return 'auth';
};

describe('anchorOf', () => {
	it('puts a step on the node it was about', () => {
		expect(anchorOf(step(1, 'work_history', { system: 'Auth' }, ['pr:1', 'system:Auth']), drawn)).toBe('system:Auth');
	});
	it('falls back to the first drawn node it returned', () => {
		expect(anchorOf(step(1, 'related_work_items', { text: 'jwt' }, ['chunk:9', 'pr:4']), drawn)).toBe('pr:4');
	});
	it('gives no point to a step spread over several territories', () => {
		expect(anchorOf(step(1, 'list_systems', {}, ['system:Auth', 'system:Billing']), drawn)).toBeNull();
	});
	it('gives no point to a step that touched nothing drawn, or is not a graph call', () => {
		expect(anchorOf(step(1, 'related_documents', { text: 'x' }, ['chunk:1']), drawn)).toBeNull();
		expect(anchorOf(step(2, 'submit_answer', {}, ['pr:1'], { kind: 'submit' }), drawn)).toBeNull();
	});
});

describe('trailOf', () => {
	it('orders points, folds repeats on one node and lights every drawn node', () => {
		const t = trailOf(
			run([
				step(1, 'work_history', { system: 'Auth' }, ['system:Auth', 'pr:1']),
				step(2, 'experts_for_system', { system: 'Auth' }, ['person:alice']),
				step(3, 'get_entity', { uid: 'pr:1' }, ['pr:1', 'chunk:2']),
				step(4, 'submit_answer', {}, [], { kind: 'submit' })
			]),
			drawn
		);
		expect(t.points).toEqual([
			{ uid: 'system:Auth', ns: [1, 2] },
			{ uid: 'pr:1', ns: [3] }
		]);
		expect([...t.lit].sort()).toEqual(['person:alice', 'pr:1', 'system:Auth']);
		expect(t.current).toBeNull();
	});
	it('lights a spread step without a point and counts it as on the map', () => {
		const r = run([step(1, 'list_systems', {}, ['system:Auth', 'system:Billing'])]);
		const t = trailOf(r, drawn);
		expect(t.points).toEqual([]);
		expect([...t.spread]).toEqual([1]);
		expect(stepsSummary(r, t)).toBe('1 step');
	});
	it('puts no ring on an old node while the latest step has no point', () => {
		const t = trailOf(
			run([step(1, 'get_entity', { uid: 'pr:1' }, ['pr:1']), step(2, 'list_systems', {}, ['system:Auth', 'system:Billing'])], 'running'),
			drawn
		);
		expect(t.current).toBeNull();
	});
	it('marks where a running run is now', () => {
		const t = trailOf(run([step(1, 'get_entity', { uid: 'pr:1' }, ['pr:1'])], 'running'), drawn);
		expect(t.current).toBe('pr:1');
	});
});

describe('words', () => {
	it('names the agents', () => {
		expect(actorName('brain')).toBe('Ask agent');
		expect(actorName('keeper')).toBe('Keeper');
		expect(actorName('robot')).toBe('robot');
	});
	it('says what a step did, or is doing', () => {
		expect(stepLine(step(1, 'work_history', { system: 'Auth' }, []))).toBe('Read recent work on Auth');
		expect(stepLine(step(1, 'work_history', { system: 'Auth' }, [], { status: 'running' }))).toBe('Reading recent work on Auth');
		expect(stepLine(step(1, 'search', {}, [], { kind: 'mcp' }))).toBe('Called search');
	});
	it('says what the agent is doing now', () => {
		expect(doingNow(run([step(1, 'impact_of', { system: 'Auth' }, [], { status: 'running' })], 'running'))).toBe(
			'Checking what changes together with Auth'
		);
		expect(doingNow(run([step(1, 'impact_of', { system: 'Auth' }, [])], 'running'))).toBe('Thinking about the next step');
	});
	it('counts steps and the ones off the map', () => {
		const r = run([step(1, 'get_entity', { uid: 'pr:1' }, ['pr:1']), step(2, 'submit_answer', {}, [], { kind: 'submit' })]);
		expect(stepsSummary(r, trailOf(r, drawn))).toBe('2 steps · 1 not on the map');
		const one = run([step(1, 'get_entity', { uid: 'pr:1' }, ['pr:1'])]);
		expect(stepsSummary(one, trailOf(one, drawn))).toBe('1 step');
	});
});

describe('shownRun', () => {
	const old = run([], 'done', 'old');
	const last = run([], 'done', 'last');
	it('keeps a pick while the featured run is the one it was picked over', () => {
		expect(shownRun([last, old], { id: 'old', featuredAt: 'last' })?.id).toBe('old');
	});
	it('lets a run that starts take the map, and keep it after it finishes', () => {
		const pick = { id: 'old', featuredAt: 'last' };
		expect(shownRun([run([], 'running', 'new'), last, old], pick)?.id).toBe('new');
		expect(shownRun([run([], 'done', 'new'), last, old], pick)?.id).toBe('new');
	});
	it('falls back to the featured run when the pick is gone', () => {
		expect(shownRun([last], { id: 'old', featuredAt: 'last' })?.id).toBe('last');
		expect(shownRun([], null)).toBeNull();
	});
});

describe('featured', () => {
	it('opens on a running run, else the newest', () => {
		const a = run([], 'done', 'a');
		const b = run([], 'running', 'b');
		expect(featured([a, b])?.id).toBe('b');
		expect(featured([a])?.id).toBe('a');
		expect(featured([])).toBeNull();
	});
});
