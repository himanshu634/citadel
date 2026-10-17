import { describe, expect, test } from 'vitest';
import {
	buildingTitle,
	peopleRows,
	sinceLabel,
	statCards,
	systemBars,
	viewOf,
	workItemOf
} from './overview';
import { statusLineOf } from './topbar';
import type { BuildSummary, Company, PersonActivity, RecentWorkItem, SystemSummary } from './types';

function company(over: Partial<Company> = {}): Company {
	return {
		slug: 'acme',
		name: 'Acme Labs',
		data_permission: 'public',
		status: 'ready',
		last_synced_at: null,
		error: null,
		build: null,
		graph_reachable: true,
		...over
	};
}

const build = (over: Partial<BuildSummary> = {}): BuildSummary => ({
	kind: 'build',
	state: 'running',
	stage: 'fetch',
	stages: ['prepare', 'fetch', 'records', 'normalize', 'load', 'done'],
	started_at: '2026-10-16T09:00:00Z',
	...over
});

describe('viewOf', () => {
	test('ready shows the data with no failure', () => {
		expect(viewOf(company())).toEqual({ kind: 'data', failure: null, building: false });
	});

	test('failed shows the data with the last build error above it', () => {
		expect(viewOf(company({ status: 'failed', error: 'fetch failed: 403' }))).toEqual({
			kind: 'data',
			failure: 'fetch failed: 403',
			building: false
		});
	});

	test('failed without an error text still says what happened', () => {
		const view = viewOf(company({ status: 'failed' }));
		expect(view).toEqual({
			kind: 'data',
			failure: 'The last build failed.',
			building: false
		});
	});

	test('invalid shows the YAML error and no data', () => {
		expect(viewOf(company({ status: 'invalid', error: 'sources.0: field required' }))).toEqual({
			kind: 'invalid',
			error: 'sources.0: field required'
		});
	});

	test('unknown means the graph is unreachable, with nothing to fetch', () => {
		expect(viewOf(company({ status: 'unknown', graph_reachable: false }))).toEqual({
			kind: 'unreachable'
		});
	});

	test('building a company that never loaded waits for the first build', () => {
		expect(viewOf(company({ status: 'building', last_synced_at: null }))).toEqual({
			kind: 'waiting'
		});
	});

	test('building over an already loaded graph keeps the overview, with the building flag', () => {
		const synced = company({ status: 'building', last_synced_at: '2026-10-16T09:12:00Z' });
		expect(viewOf(synced)).toEqual({ kind: 'data', failure: null, building: true });
	});

	test('empty waits for a first build', () => {
		expect(viewOf(company({ status: 'empty' })).kind).toBe('waiting');
	});
});

describe('buildingTitle', () => {
	test('counts the step over the planned stages, not a fixed four', () => {
		const c = company({ status: 'building', build: build({ stage: 'records' }) });
		expect(buildingTitle(c)).toBe('Building, step 3 of 5');
	});

	test('says Building alone with no build or no known stage', () => {
		expect(buildingTitle(company({ status: 'building' }))).toBe('Building');
		expect(buildingTitle(company({ status: 'building', build: build({ stage: null }) }))).toBe(
			'Building'
		);
	});

	test('decides from the status, not from a finished build', () => {
		const done = build({ state: 'done', stage: 'done' });
		expect(buildingTitle(company({ status: 'building', build: done }))).toBe('Building');
	});

	test('an unbuilt company with nothing running is not "building"', () => {
		expect(buildingTitle(company({ status: 'empty' }))).toBe('Not built yet');
	});
});

test('the overview banner and the top bar word a build in progress the same way', () => {
	const rows = [
		company({ status: 'building' }),
		company({ status: 'building', build: build({ stage: null }) }),
		company({ status: 'building', build: build({ stage: 'load' }) })
	];
	for (const c of rows) expect(buildingTitle(c)).toBe(statusLineOf(c)?.text);
});

describe('statCards', () => {
	test('keeps the graph labels people know, in a fixed order, with their plural names', () => {
		const cards = statCards([
			{ kind: 'node', type: 'Document', count: 3 },
			{ kind: 'node', type: 'Chunk', count: 40 },
			{ kind: 'node', type: 'WorkItem', count: 15 },
			{ kind: 'node', type: 'Person', count: 5 }
		]);
		expect(cards).toEqual([
			{ type: 'person', label: 'People', value: 5 },
			{ type: 'work-item', label: 'Work items', value: 15 },
			{ type: 'document', label: 'Documents', value: 3 }
		]);
	});

	test('is empty for an empty graph', () => {
		expect(statCards([])).toEqual([]);
	});
});

describe('workItemOf', () => {
	const item: RecentWorkItem = {
		uid: 'x:pr:1',
		kind: 'pull_request',
		number: 1,
		title: 'feat(auth): JWT',
		state: 'merged',
		url: 'https://example.com/1',
		author: 'alice',
		last_at: '2026-02-06T10:00:00Z',
		systems: ['Auth', 'Web app']
	};

	test('maps the API row to the row component', () => {
		expect(workItemOf(item)).toEqual({
			uid: 'x:pr:1',
			kind: 'pull_request',
			number: 1,
			title: 'feat(auth): JWT',
			state: 'merged',
			author: 'alice',
			date: '2026-02-06T10:00:00Z',
			system: 'Auth, Web app',
			url: 'https://example.com/1'
		});
	});

	test('a GitHub item with no url still opens on GitHub; an unsafe url is dropped', () => {
		expect(workItemOf({ ...item, uid: 'github:o/r:issue:4', url: null }).url).toBe('https://github.com/o/r/issues/4');
		expect(workItemOf({ ...item, url: 'javascript:alert(1)' }).url).toBeUndefined();
	});

	test('leaves out what the API has not got', () => {
		const bare = workItemOf({ ...item, number: null, url: null, author: null, last_at: null, systems: [] });
		expect(bare.number).toBeUndefined();
		expect(bare.author).toBeUndefined();
		expect(bare.date).toBeUndefined();
		expect(bare.system).toBeUndefined();
		expect(bare.url).toBeUndefined();
	});
});

describe('systemBars and peopleRows', () => {
	test('a system is a bar labelled by its owners', () => {
		const systems: SystemSummary[] = [
			{ system: 'Auth', system_uid: 'system:Auth', path_rule: null, changes: 9, people: 3, owners: ['identity'] },
			{ system: 'Infra', system_uid: 'system:Infra', path_rule: null, changes: 3, people: 1, owners: [] }
		];
		expect(systemBars(systems)).toEqual([
			{ label: 'Auth', value: 9, meta: 'identity' },
			{ label: 'Infra', value: 3, meta: 'no owner' }
		]);
	});

	test('a person shows the display name, teams and singular or plural counts', () => {
		const people: PersonActivity[] = [
			{ login: 'alice', person_uid: 'person:alice', display_name: 'Alice Kim', teams: ['identity'], prs: 2, reviews: 1 },
			{ login: 'zed', person_uid: 'person:zed', display_name: null, teams: [], prs: 1, reviews: 0 }
		];
		expect(peopleRows(people)).toEqual([
			{ key: 'person:alice', name: 'Alice Kim', meta: 'identity, 2 PRs, 1 review' },
			{ key: 'person:zed', name: 'zed', meta: '1 PR, 0 reviews' }
		]);
	});
});

describe('sinceLabel', () => {
	test('writes a calendar date without shifting the day by time zone', () => {
		expect(sinceLabel('2026-01-01')).toBe('1 Jan 2026');
		expect(sinceLabel('2025-10-31')).toBe('31 Oct 2025');
	});

	test('returns text that is not a date unchanged', () => {
		expect(sinceLabel('soon')).toBe('soon');
	});
});
