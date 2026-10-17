import { describe, expect, test } from 'vitest';
import { buildTable, stepOf } from './build';
import type { BuildEvent, BuildStage, BuildStatus, BuildSummary } from './types';

function ev(
	stage: BuildStage,
	status: BuildStatus,
	source: string | null = null,
	count?: number,
	message?: string
): BuildEvent {
	return {
		slug: 'acme',
		stage,
		status,
		source,
		count: count ?? null,
		message: message ?? null,
		at: '2026-10-16T10:00:00+00:00',
		totals: null
	};
}

describe('buildTable', () => {
	test('takes the latest event per cell', () => {
		const t = buildTable([
			ev('fetch', 'running', 'github:a/b'),
			ev('fetch', 'done', 'github:a/b', 2310),
			ev('records', 'skipped', 'local_docs:docs', undefined, 'Folder not found')
		]);
		expect(t.rows.map((r) => r.source)).toEqual(['github:a/b', 'local_docs:docs']);
		expect(t.rows[0].fetch).toEqual({ status: 'done', count: 2310 });
		expect(t.rows[0].load.status).toBe('waiting');
		expect(t.rows[1].records.message).toBe('Folder not found');
	});

	test('keeps prepare and reset apart from the source rows', () => {
		const t = buildTable([ev('prepare', 'done'), ev('reset', 'done'), ev('done', 'done')]);
		expect(t.prepare.status).toBe('done');
		expect(t.reset).toEqual({ status: 'done' });
		expect(t.rows).toEqual([]);
	});

	test('prepare is waiting before its event; reset appears only when it exists', () => {
		expect(buildTable([]).prepare).toEqual({ status: 'waiting' });
		expect(buildTable([]).reset).toBeUndefined();
	});

	test('embed is one cell for the whole company, after every source', () => {
		const plan: BuildStage[] = ['prepare', 'fetch', 'records', 'normalize', 'load', 'embed'];
		const t = buildTable(
			[
				ev('load', 'done', 'github:a/b', 90),
				ev('embed', 'running'),
				ev('embed', 'running', null, 64),
				ev('embed', 'done', null, 120)
			],
			plan
		);
		expect(t.embed).toEqual({ status: 'done', count: 120 });
		expect(t.rows.map((r) => r.source)).toEqual(['github:a/b']); // not a source row
		expect(buildTable([ev('prepare', 'running')], plan).embed).toEqual({ status: 'waiting' });
	});

	test('embed running says the model is loading until the first count', () => {
		const loading = ev('embed', 'running', null, undefined, 'Loading the embedding model');
		expect(buildTable([loading]).embed).toEqual({ status: 'running', message: 'Loading the embedding model' });
		expect(buildTable([loading, ev('embed', 'running', null, 64)]).embed).toEqual({ status: 'running', count: 64 });
	});

	test('embed skipped keeps its reason', () => {
		const t = buildTable([ev('embed', 'skipped', null, undefined, 'Embeddings are off')]);
		expect(t.embed).toEqual({ status: 'skipped', message: 'Embeddings are off' });
	});

	test('a build planned before embed existed has no embed cell', () => {
		expect(buildTable([ev('prepare', 'done')], ['prepare', 'fetch', 'records', 'normalize', 'load']).embed).toBe(
			undefined
		);
	});

	test('a stop during embed lands on the embed cell, not on a source stage', () => {
		const t = buildTable([ev('embed', 'running', null, 64), ev('embed', 'stopped')]);
		expect(t.embed).toEqual({ status: 'stopped' });
		expect(t.closing).toBeUndefined();
	});

	test('the planned stages decide which stage cells exist', () => {
		const events = [ev('prepare', 'running')];
		// A build plans no reset; a rebuild does.
		expect(buildTable(events, ['prepare', 'fetch', 'records', 'normalize', 'load']).reset).toBe(
			undefined
		);
		expect(buildTable(events, ['reset', 'prepare', 'records', 'normalize', 'load']).reset).toEqual({
			status: 'waiting'
		});
	});

	test('a rebuild without refetch marks the fetch cells skipped, without a message', () => {
		const t = buildTable(
			[ev('reset', 'done'), ev('prepare', 'done'), ev('records', 'running', 'github:a/b')],
			['reset', 'prepare', 'records', 'normalize', 'load']
		);
		expect(t.rows[0].fetch).toEqual({ status: 'skipped' });
		expect(t.rows[0].records.status).toBe('running');
		// A fetch event that did arrive still wins over the plan.
		const withFetch = buildTable([ev('fetch', 'done', 'github:a/b', 5)], ['prepare', 'records']);
		expect(withFetch.rows[0].fetch).toEqual({ status: 'done', count: 5 });
	});

	test('a source without a fetch event but with a later stage is skipped (partial refetch)', () => {
		const t = buildTable(
			[
				ev('fetch', 'done', 'github:a/b', 7),
				ev('records', 'done', 'github:a/b', 7),
				ev('records', 'running', 'local_docs:docs')
			],
			['prepare', 'fetch', 'records', 'normalize', 'load']
		);
		expect(t.rows[0].fetch).toEqual({ status: 'done', count: 7 });
		expect(t.rows[1].fetch).toEqual({ status: 'skipped' });
		// Still waiting when the source has not reached any later stage.
		const early = buildTable([ev('fetch', 'running', 'github:a/b'), ev('fetch', 'done', 'github:c/d')]);
		expect(early.rows.map((r) => r.fetch.status)).toEqual(['running', 'done']);
	});

	test('a source-less failure closes the table and stops the running cells of its stage', () => {
		const t = buildTable([
			ev('records', 'done', 'github:a/b', 3),
			ev('normalize', 'running', 'github:a/b'),
			ev('records', 'done', 'local_docs:docs', 1),
			ev('normalize', 'failed', null, undefined, 'boom')
		]);
		expect(t.closing).toEqual({ stage: 'normalize', status: 'failed', message: 'boom' });
		expect(t.rows[0].normalize).toEqual({ status: 'failed' });
		expect(t.rows[1].normalize).toEqual({ status: 'failed' });
		expect(t.rows[0].records).toEqual({ status: 'done', count: 3 });
		expect(t.rows[1].load.status).toBe('waiting');
	});

	test('a stop between sources closes without a message and keeps finished cells', () => {
		const t = buildTable([
			ev('fetch', 'done', 'github:a/b', 2),
			ev('fetch', 'running', 'github:c/d'),
			ev('fetch', 'stopped')
		]);
		expect(t.closing).toEqual({ stage: 'fetch', status: 'stopped' });
		expect(t.rows[0].fetch).toEqual({ status: 'done', count: 2 });
		expect(t.rows[1].fetch).toEqual({ status: 'stopped' });
	});

	test('a failure before any source event shows in closing; prepare failures stay in prepare', () => {
		const t = buildTable([ev('prepare', 'done'), ev('records', 'failed', null, undefined, 'x')]);
		expect(t.closing).toEqual({ stage: 'records', status: 'failed', message: 'x' });
		expect(t.rows).toEqual([]);
		const p = buildTable([ev('prepare', 'failed', null, undefined, 'no db')]);
		expect(p.prepare).toEqual({ status: 'failed', message: 'no db' });
		expect(p.closing).toBeUndefined();
	});

	test('a source-less table has its source rows only from events', () => {
		expect(buildTable([], ['prepare', 'fetch', 'records', 'normalize', 'load']).rows).toEqual([]);
	});
});

describe('stepOf', () => {
	const summary = (over: Partial<BuildSummary>): BuildSummary => ({
		kind: 'build',
		state: 'running',
		stage: 'fetch',
		stages: ['prepare', 'fetch', 'records', 'normalize', 'load', 'done'],
		started_at: '2026-10-16T10:00:00+00:00',
		...over
	});

	test('counts the stage within the planned stages, without done', () => {
		expect(stepOf(summary({}))).toEqual({ n: 2, total: 5 });
		expect(stepOf(summary({ stage: 'load' }))).toEqual({ n: 5, total: 5 });
		const rebuild = summary({
			kind: 'rebuild',
			stage: 'reset',
			stages: ['reset', 'prepare', 'records', 'normalize', 'load']
		});
		expect(stepOf(rebuild)).toEqual({ n: 1, total: 5 });
	});

	test('is null when nothing is building or the stage is unknown', () => {
		expect(stepOf(summary({ state: 'done', stage: 'done' }))).toBeNull();
		expect(stepOf(summary({ state: 'failed' }))).toBeNull();
		expect(stepOf(summary({ state: 'queued', stage: null }))).toBeNull();
		expect(stepOf(summary({ stage: 'done' }))).toBeNull();
		expect(stepOf(summary({ stage: 'reset' }))).toBeNull();
	});

	test("uses the backend's step counter when the summary has one", () => {
		// Two sources: the second source's records is step 7 of 9, not "step 3" again.
		expect(stepOf(summary({ stage: 'records', step: 7, steps: 9 }))).toEqual({ n: 7, total: 9 });
		expect(stepOf(summary({ stage: 'load', step: 9, steps: 9 }))).toEqual({ n: 9, total: 9 });
	});

	test('with a counter: null while queued, before the first step, or once the build ended', () => {
		expect(stepOf(summary({ state: 'queued', stage: 'prepare', step: null, steps: 9 }))).toBeNull();
		expect(stepOf(summary({ step: null, steps: 9 }))).toBeNull();
		expect(stepOf(summary({ state: 'done', stage: 'done', step: 9, steps: 9 }))).toBeNull();
		expect(stepOf(summary({ state: 'stopped', step: 4, steps: 9 }))).toBeNull();
	});

	test('without a counter (an old build file) falls back to the stage index', () => {
		expect(stepOf(summary({ step: null, steps: null }))).toEqual({ n: 2, total: 5 });
	});
});
