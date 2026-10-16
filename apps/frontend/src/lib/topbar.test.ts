import { describe, expect, test } from 'vitest';
import { askFieldOf, formatSynced, statusLineOf } from './topbar';
import type { BuildSummary, Company } from './types';

const NOW = new Date(2026, 9, 16, 12, 0);
const local = (y: number, m: number, d: number, h: number, min: number) =>
	new Date(y, m, d, h, min).toISOString();

function company(over: Partial<Company> = {}): Company {
	return {
		slug: 'acme',
		name: 'Acme Labs',
		data_permission: 'public',
		status: 'ready',
		last_synced_at: local(2026, 1, 6, 14, 32),
		error: null,
		build: null,
		graph_reachable: true,
		...over
	};
}

const running = (stage: BuildSummary['stage'], stages: BuildSummary['stages']): BuildSummary => ({
	state: 'running',
	stage,
	started_at: local(2026, 9, 16, 11, 0),
	kind: 'build',
	stages
});

describe('formatSynced', () => {
	test('day, short month and 24-hour time, in local time', () => {
		expect(formatSynced(local(2026, 1, 6, 14, 32), NOW)).toBe('6 Feb, 14:32');
		expect(formatSynced(local(2026, 9, 16, 9, 5), NOW)).toBe('16 Oct, 09:05');
	});

	test('a year other than this one is shown', () => {
		expect(formatSynced(local(2025, 8, 3, 23, 59), NOW)).toBe('3 Sep 2025, 23:59');
	});

	test('an unreadable date gives nothing', () => {
		expect(formatSynced('not a date', NOW)).toBeNull();
	});
});

describe('askFieldOf', () => {
	test('ready: asks the company', () => {
		expect(askFieldOf(company())).toEqual({
			disabled: false,
			placeholder: 'Ask Acme Labs about people, systems or decisions'
		});
	});

	test('building and empty: closed until the first build ends', () => {
		for (const status of ['building', 'empty'] as const) {
			expect(askFieldOf(company({ status }))).toEqual({
				disabled: true,
				placeholder: 'Asking opens when Acme Labs finishes building'
			});
		}
	});

	test('invalid and unknown say what to fix', () => {
		expect(askFieldOf(company({ status: 'invalid' }))).toEqual({
			disabled: true,
			placeholder: 'Fix the config to ask Acme Labs'
		});
		expect(askFieldOf(company({ status: 'unknown' }))).toEqual({
			disabled: true,
			placeholder: "Asking opens when Acme Labs's graph is reachable"
		});
	});

	test('failed keeps asking the graph it has', () => {
		expect(askFieldOf(company({ status: 'failed' })).disabled).toBe(false);
	});

	test('no company: closed', () => {
		expect(askFieldOf(undefined)).toEqual({
			disabled: true,
			placeholder: 'Open a company to ask about it'
		});
	});
});

describe('statusLineOf', () => {
	test('ready shows when it last synced', () => {
		const line = statusLineOf(company(), NOW);
		expect(line).toMatchObject({ text: 'Synced 6 Feb, 14:32', tone: 'muted' });
		expect(line?.datetime).toBe(company().last_synced_at);
	});

	test('ready without a sync date', () => {
		expect(statusLineOf(company({ last_synced_at: null }), NOW)?.text).toBe('Not synced yet');
	});

	test('building counts steps from the planned stages, not a fixed four', () => {
		const stages: BuildSummary['stages'] = [
			'prepare',
			'reset',
			'fetch',
			'records',
			'normalize',
			'load',
			'done'
		];
		const line = statusLineOf(
			company({ status: 'building', build: running('fetch', stages) }),
			NOW
		);
		expect(line).toMatchObject({
			text: 'Building, step 3 of 6',
			tone: 'warning'
		});
	});

	test('building without a known stage', () => {
		expect(statusLineOf(company({ status: 'building', build: null }), NOW)?.text).toBe('Building');
		const queued = {
			...running(null, ['prepare', 'fetch', 'done']),
			state: 'queued' as const
		};
		expect(statusLineOf(company({ status: 'building', build: queued }), NOW)?.text).toBe(
			'Building'
		);
	});

	test('status comes from the company, not from a finished build', () => {
		const done = {
			...running('done', ['prepare', 'done']),
			state: 'done' as const
		};
		expect(statusLineOf(company({ build: done }), NOW)?.text).toBe('Synced 6 Feb, 14:32');
	});

	test('the other states', () => {
		expect(statusLineOf(company({ status: 'failed' }), NOW)).toMatchObject({
			text: 'Last build failed',
			tone: 'danger'
		});
		expect(statusLineOf(company({ status: 'empty' }), NOW)?.text).toBe('Not built yet');
		expect(statusLineOf(company({ status: 'invalid' }), NOW)).toMatchObject({
			text: 'Config invalid',
			tone: 'danger'
		});
		expect(statusLineOf(company({ status: 'unknown' }), NOW)).toMatchObject({
			text: 'Graph unreachable',
			tone: 'muted'
		});
	});

	test('no company: no status', () => {
		expect(statusLineOf(undefined, NOW)).toBeNull();
	});
});
