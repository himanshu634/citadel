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
});
