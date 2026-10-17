import { describe, expect, test } from 'vitest';
import {
	cellNote,
	endsBuild,
	headerOf,
	isActive,
	logLine,
	percentOf,
	rowView,
	sourceLabel,
	titleOf,
	withEvent
} from './buildProgress';
import { buildTable } from './build';
import type { BuildEvent, BuildSnapshot, BuildStage, BuildState, BuildStatus } from './types';

function ev(
	stage: BuildStage,
	status: BuildStatus,
	source: string | null = null,
	count?: number,
	message?: string,
	at = '2026-10-16T10:00:00+00:00'
): BuildEvent {
	return {
		slug: 'acme',
		stage,
		status,
		source,
		count: count ?? null,
		message: message ?? null,
		at,
		totals: null
	};
}

const BUILD_STAGES: BuildStage[] = ['prepare', 'fetch', 'records', 'normalize', 'load', 'embed'];
const REBUILD_STAGES: BuildStage[] = ['reset', ...BUILD_STAGES];

function snap(
	events: BuildEvent[],
	state: BuildState = 'running',
	extra: Partial<BuildSnapshot> = {}
): BuildSnapshot {
	return {
		slug: 'acme',
		kind: 'build',
		state,
		started_at: '2026-10-16T10:00:00+00:00',
		stages: BUILD_STAGES,
		ended_at: state === 'running' || state === 'queued' ? null : '2026-10-16T10:05:00+00:00',
		events,
		error: null,
		...extra
	};
}

/** The events of a build of two sources, in the order the pipeline emits them. */
function twoSources(): BuildEvent[] {
	const a = 'github:acme/platform';
	const b = 'github:acme/web';
	return [
		ev('prepare', 'running'),
		ev('prepare', 'done'),
		ev('fetch', 'running', a),
		ev('fetch', 'done', a),
		ev('fetch', 'running', b),
		ev('fetch', 'done', b),
		ev('records', 'running', a),
		ev('records', 'done', a, 100),
		ev('normalize', 'done', a, 90),
		ev('load', 'running', a),
		ev('load', 'done', a, 90),
		ev('records', 'running', b),
		ev('records', 'done', b, 40),
		ev('normalize', 'done', b, 30),
		ev('load', 'running', b),
		ev('load', 'done', b, 30),
		ev('embed', 'running'),
		ev('embed', 'running', null, 64),
		ev('embed', 'done', null, 120)
	];
}

/** What the backend stamps on `twoSources()`: each (stage, source), and embed, is one step of 10. */
const TWO_SOURCE_STEPS = [1, 1, 2, 2, 3, 3, 4, 4, 5, 6, 6, 7, 7, 8, 9, 9, 10, 10, 10];

function twoSourcesStamped(): BuildEvent[] {
	return twoSources().map((event, i) => ({ ...event, step: TWO_SOURCE_STEPS[i] }));
}

describe('states', () => {
	test('queued and running are active', () => {
		expect(['queued', 'running', 'done', 'failed', 'stopped'].map((s) => isActive(s as BuildState))).toEqual([
			true,
			true,
			false,
			false,
			false
		]);
	});

	test('endsBuild mirrors the backend: done stage, or any failed or stopped event', () => {
		expect(endsBuild(ev('done', 'done'))).toBe(true);
		expect(endsBuild(ev('fetch', 'failed', 'github:a/b'))).toBe(true);
		expect(endsBuild(ev('load', 'stopped'))).toBe(true);
		expect(endsBuild(ev('load', 'done', 'github:a/b'))).toBe(false);
		expect(endsBuild(ev('records', 'skipped', 'local_docs:docs'))).toBe(false);
	});
});

describe('withEvent', () => {
	test('appends an event of the same build', () => {
		const next = withEvent(snap([ev('prepare', 'running')]), ev('prepare', 'done'));
		expect(next.events.map((e) => e.status)).toEqual(['running', 'done']);
	});

	test('ignores an event it already holds and one of another company', () => {
		const held = snap([ev('prepare', 'running')]);
		expect(withEvent(held, ev('prepare', 'running'))).toBe(held);
		expect(withEvent(held, { ...ev('prepare', 'done'), slug: 'other' })).toBe(held);
	});

	test('a later event with the same text but another time is kept', () => {
		const held = snap([ev('prepare', 'running')]);
		const next = withEvent(held, ev('prepare', 'running', null, undefined, undefined, '2026-10-16T10:00:09+00:00'));
		expect(next.events).toHaveLength(2);
	});
});

describe('withEvent and the step counter', () => {
	test("takes the event's step, so a live stream keeps the count", () => {
		const held = snap([ev('prepare', 'running')], 'running', { step: 1, steps: 9 });
		const next = withEvent(held, { ...ev('fetch', 'running', 'github:acme/platform'), step: 2 });
		expect([next.step, next.steps]).toEqual([2, 9]);
	});

	test('an event without a step leaves the counter as it is', () => {
		const held = snap([ev('prepare', 'running')], 'running', { step: 1, steps: 9 });
		expect(withEvent(held, ev('prepare', 'done')).step).toBe(1);
	});
});

describe('two sources: header and meter agree', () => {
	test('neither the step nor the meter ever goes back, and the count is per source', () => {
		const events = twoSourcesStamped();
		let live = snap([], 'running', { step: 1, steps: 10 });
		let lastStep = 0;
		let lastPercent = 0;
		const headers: string[] = [];
		for (const event of events) {
			live = withEvent(live, event);
			const header = headerOf(live);
			headers.push(header);
			const n = Number(/^Step (\d+) of 10: /.exec(header)?.[1]);
			expect(n).toBeGreaterThanOrEqual(lastStep);
			const percent = percentOf(live);
			expect(percent).toBeGreaterThanOrEqual(lastPercent);
			lastStep = n;
			lastPercent = percent;
		}
		expect(headers[11]).toBe('Step 7 of 10: records'); // the second source, not "Step 3" again
		expect(headers[15]).toBe('Step 9 of 10: load');
		expect(headers.at(-1)).toBe('Step 10 of 10: embed');
	});
});

describe('headerOf', () => {
	test('running: step n of N and the stage, counting a rebuild\'s reset and prepare', () => {
		const build = snap([ev('prepare', 'done'), ev('records', 'running', 'github:a/b')]);
		expect(headerOf(build)).toBe('Step 3 of 6: records');
		const rebuild = snap([ev('reset', 'done'), ev('prepare', 'running')], 'running', {
			kind: 'rebuild',
			stages: REBUILD_STAGES
		});
		expect(headerOf(rebuild)).toBe('Step 2 of 7: prepare');
	});

	test('a rebuild that fetches nothing plans no fetch step', () => {
		const rebuild = snap([ev('records', 'running', 'github:a/b')], 'running', {
			kind: 'rebuild',
			stages: ['reset', 'prepare', 'records', 'normalize', 'load']
		});
		expect(headerOf(rebuild)).toBe('Step 3 of 5: records');
	});

	test('queued, and running before any event or with an unplanned stage', () => {
		expect(headerOf(snap([ev('prepare', 'waiting')], 'queued'))).toBe(
			'Queued, waiting for another build to finish'
		);
		expect(headerOf(snap([]))).toBe('Building');
	});

	test('stopping shows until the build has stopped', () => {
		expect(headerOf(snap([ev('fetch', 'running', 'github:a/b')]), true)).toBe(
			'Stopping after the current step'
		);
		expect(headerOf(snap([ev('fetch', 'stopped', 'github:a/b')], 'stopped'), true)).toBe(
			'Build stopped at fetch'
		);
	});

	test('finished, failed and stopped builds say how they ended', () => {
		expect(headerOf(snap([ev('done', 'done')], 'done'))).toBe('Build finished');
		expect(headerOf(snap([ev('done', 'done')], 'done', { kind: 'rebuild' }))).toBe('Rebuild finished');
		expect(headerOf(snap([ev('load', 'failed', 'github:a/b')], 'failed'))).toBe('Build failed at load');
		expect(headerOf(snap([], 'failed', { kind: 'rebuild' }))).toBe('Rebuild failed');
		expect(headerOf(snap([ev('records', 'stopped')], 'stopped'))).toBe('Build stopped at records');
	});
});

describe('titleOf', () => {
	test('names the company and what is happening to it', () => {
		expect(titleOf('Acme Labs', snap([]))).toBe('Building Acme Labs');
		expect(titleOf('Acme Labs', snap([], 'queued', { kind: 'rebuild' }))).toBe('Rebuilding Acme Labs');
		expect(titleOf('Acme Labs', snap([], 'done'))).toBe('Built Acme Labs');
		expect(titleOf('Acme Labs', snap([], 'failed'))).toBe('Build of Acme Labs failed');
		expect(titleOf('Acme Labs', snap([], 'stopped', { kind: 'rebuild' }))).toBe(
			'Rebuild of Acme Labs stopped'
		);
	});
});

describe('percentOf', () => {
	test('is 0 before anything ran and 100 only when the build is done', () => {
		expect(percentOf(snap([]))).toBe(0);
		const all = twoSources();
		expect(percentOf(snap(all, 'running'))).toBeLessThan(100);
		expect(percentOf(snap([...all, ev('done', 'done')], 'done'))).toBe(100);
	});

	test('never goes down while a two-source build runs, and ends below 100 until done', () => {
		const all = twoSources();
		let last = -1;
		for (let n = 0; n <= all.length; n++) {
			const p = percentOf(snap(all.slice(0, n)));
			expect(p).toBeGreaterThanOrEqual(last);
			expect(p).toBeLessThan(100);
			last = p;
		}
		expect(last).toBeGreaterThan(50);
	});

	test('a failed build keeps what it had reached', () => {
		const events = [...twoSources().slice(0, 8), ev('records', 'failed', 'github:acme/platform')];
		const running = percentOf(snap(events.slice(0, 8)));
		expect(percentOf(snap(events, 'failed'))).toBe(running);
	});

	test('embed counts as work: finishing it moves the meter', () => {
		const all = twoSources();
		const beforeEmbed = percentOf(snap(all.slice(0, -3)));
		expect(percentOf(snap(all))).toBeGreaterThan(beforeEmbed);
		expect(percentOf(snap(all.slice(0, -1)))).toBe(beforeEmbed); // running is not finished
	});

	test('a skipped source counts as finished work', () => {
		const events = [
			ev('prepare', 'done'),
			ev('fetch', 'done', 'github:a/b'),
			ev('records', 'skipped', 'local_docs:docs', undefined, 'Folder not found')
		];
		const withSkip = percentOf(snap(events));
		const without = percentOf(snap(events.slice(0, 2)));
		expect(withSkip).toBeGreaterThan(without);
	});
});

describe('rowView', () => {
	const rowOf = (events: BuildEvent[]) => buildTable(events, BUILD_STAGES).rows[0];

	test('a running row is four single cells', () => {
		const parts = rowView(
			rowOf([ev('fetch', 'done', 'github:a/b', 5), ev('records', 'running', 'github:a/b')])
		);
		expect(parts.map((p) => p.stages)).toEqual([['fetch'], ['records'], ['normalize'], ['load']]);
		expect(parts[1].cell.status).toBe('running');
	});

	test('records skipped with a message cannot reach normalize or load: one skipped cell spans them', () => {
		const parts = rowView(
			rowOf([
				ev('fetch', 'done', 'local_docs:docs'),
				ev('records', 'skipped', 'local_docs:docs', undefined, 'Folder not found')
			])
		);
		expect(parts.map((p) => p.stages)).toEqual([['fetch'], ['records', 'normalize', 'load']]);
		expect(parts[1].cell).toEqual({ status: 'skipped', message: 'Folder not found' });
	});

	test('a source with no adapter is skipped from its first cell: the whole row is one cell', () => {
		const parts = rowView(
			rowOf([
				ev('fetch', 'skipped', 'jira', undefined, 'No adapter'),
				ev('records', 'skipped', 'jira', undefined, 'No adapter')
			])
		);
		expect(parts).toHaveLength(1);
		expect(parts[0].stages).toEqual(['fetch', 'records', 'normalize', 'load']);
		expect(parts[0].cell.message).toBe('No adapter');
	});

	test('a skipped fetch without a message (a rebuild) does not merge anything', () => {
		const table = buildTable(
			[ev('records', 'running', 'github:a/b')],
			['reset', 'prepare', 'records', 'normalize', 'load']
		);
		const parts = rowView(table.rows[0]);
		expect(parts).toHaveLength(4);
		expect(parts[0].cell).toEqual({ status: 'skipped' });
	});

	test('a failed or stopped row keeps its waiting cells waiting', () => {
		const parts = rowView(rowOf([ev('fetch', 'failed', 'github:a/b', undefined, 'rate limited')]));
		expect(parts.map((p) => p.cell.status)).toEqual(['failed', 'waiting', 'waiting', 'waiting']);
	});
});

describe('cellNote', () => {
	test('puts a unit on the count of each stage, with thousands separators', () => {
		expect(cellNote('fetch', { status: 'done', count: 2310 })).toBe('2,310 items');
		expect(cellNote('records', { status: 'running', count: 1204 })).toBe('1,204 read');
		expect(cellNote('normalize', { status: 'done', count: 90 })).toBe('90 kept');
		expect(cellNote('load', { status: 'done', count: 1 })).toBe('1 written');
		expect(cellNote('embed', { status: 'running', count: 1280 })).toBe('1,280 embedded');
	});

	test('embed skipped says why', () => {
		const reason = 'Embeddings are off (EMBEDDING_PROVIDER=none), so semantic search finds nothing.';
		expect(cellNote('embed', { status: 'skipped', message: reason })).toBe(reason);
		expect(cellNote('embed', { status: 'skipped', count: 4, message: 'onnx went away' })).toBe(
			'4 embedded, onnx went away'
		);
	});

	test('adds the message, and is empty for a bare cell', () => {
		expect(cellNote('fetch', { status: 'failed', message: 'rate limited' })).toBe('rate limited');
		expect(cellNote('records', { status: 'done', count: 3, message: 'partial' })).toBe(
			'3 read, partial'
		);
		expect(cellNote('load', { status: 'waiting' })).toBe('');
	});
});

describe('logLine', () => {
	test('formats the time as local HH:MM:SS and fills the columns', () => {
		const at = new Date(2026, 9, 16, 9, 41, 2).toISOString();
		const line = logLine(ev('fetch', 'done', 'github:acme/platform', 2310, undefined, at));
		expect(line).toEqual({
			time: '09:41:02',
			stage: 'fetch',
			status: 'done',
			source: 'github acme/platform',
			detail: '2,310 items'
		});
	});

	test('a company-level event has no source; a message is the detail; a bad time is empty', () => {
		const line = logLine(ev('prepare', 'failed', null, undefined, 'FalkorDB is down', 'not a date'));
		expect(line).toMatchObject({ time: '', source: '', detail: 'FalkorDB is down' });
	});
});

describe('sourceLabel', () => {
	test('names the known source types and keeps the rest of the key as detail', () => {
		expect(sourceLabel('github:FalkorDB/FalkorDB')).toEqual({ name: 'GitHub', detail: 'FalkorDB/FalkorDB' });
		expect(sourceLabel('local_docs:data/inbox/acme/docs')).toEqual({
			name: 'Documents folder',
			detail: 'data/inbox/acme/docs'
		});
	});

	test('falls back to the type in words, and handles a key without detail', () => {
		expect(sourceLabel('canonical_jsonl:examples/x.jsonl').name).toBe('Canonical JSONL');
		expect(sourceLabel('jira_cloud:ACME')).toEqual({ name: 'Jira cloud', detail: 'ACME' });
		expect(sourceLabel('jira')).toEqual({ name: 'Jira', detail: '' });
	});
});
