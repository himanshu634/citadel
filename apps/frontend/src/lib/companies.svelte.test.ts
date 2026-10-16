import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import type { Company, CompanyStatus } from './types';

vi.mock('./api/client', () => ({ api: { companies: vi.fn() } }));
vi.mock('./api/events', () => ({ openEvents: vi.fn() }));

import { api } from './api/client';
import { openEvents } from './api/events';
import { Companies } from './companies.svelte';

const companies = vi.mocked(api.companies);
const events = vi.mocked(openEvents);

function co(slug: string, status: CompanyStatus = 'ready', name = slug): Company {
	return {
		slug,
		name,
		data_permission: status === 'invalid' ? null : 'public',
		status,
		last_synced_at: null,
		error: null,
		build: null,
		graph_reachable: true
	};
}

beforeEach(() => {
	companies.mockReset();
	events.mockReset();
});
afterEach(() => vi.restoreAllMocks());

describe('guard', () => {
	test('drops a response for another company', () => {
		const c = new Companies();
		c.current = 'synthetic';
		expect(c.guard('falkordb', { slug: 'falkordb', n: 1 })).toBeNull();
		expect(c.guard('synthetic', { slug: 'synthetic', n: 1 })).toEqual({ slug: 'synthetic', n: 1 });
	});

	test('drops a response that arrives after the user switched away', () => {
		const c = new Companies();
		c.current = 'falkordb';
		const asked = 'falkordb';
		c.current = 'synthetic';
		expect(c.guard(asked, { slug: 'falkordb' })).toBeNull();
	});

	test('drops a response whose own slug differs from the one asked for', () => {
		const c = new Companies();
		c.current = 'a';
		expect(c.guard('a', { slug: 'b' })).toBeNull();
	});

	test('drops everything when no company is current', () => {
		const c = new Companies();
		expect(c.guard('a', { slug: 'a' })).toBeNull();
	});
});

describe('currentCompany', () => {
	test('is the list entry for current, else undefined', () => {
		const c = new Companies();
		c.list = [co('a'), co('b')];
		expect(c.currentCompany).toBeUndefined();
		c.current = 'b';
		expect(c.currentCompany?.slug).toBe('b');
		c.current = 'gone';
		expect(c.currentCompany).toBeUndefined();
		expect(c.byslug('a')?.slug).toBe('a');
	});
});

describe('apply', () => {
	test('replaces one company by slug', () => {
		const c = new Companies();
		c.list = [co('a'), co('b')];
		c.apply({ ...co('b', 'building'), build: null });
		expect(c.list.map((x) => x.status)).toEqual(['ready', 'building']);
	});

	test('adds an unknown company in API order (by name, case-insensitive)', () => {
		const c = new Companies();
		c.list = [co('a', 'ready', 'Alpha'), co('c', 'ready', 'charlie')];
		c.apply(co('b', 'ready', 'Bravo'));
		expect(c.list.map((x) => x.slug)).toEqual(['a', 'b', 'c']);
	});

	test('lists invalid companies after valid ones, by slug', () => {
		const c = new Companies();
		c.list = [co('a', 'ready', 'Alpha'), co('z', 'ready', 'Zed')];
		c.apply(co('m', 'invalid', 'm'));
		c.apply(co('b', 'invalid', 'b'));
		expect(c.list.map((x) => x.slug)).toEqual(['a', 'z', 'b', 'm']);
	});

	test('re-sorts when a rename changes the name', () => {
		const c = new Companies();
		c.list = [co('a', 'ready', 'Alpha'), co('b', 'ready', 'Bravo')];
		c.apply(co('a', 'ready', 'Zulu'));
		expect(c.list.map((x) => x.slug)).toEqual(['b', 'a']);
	});
});

describe('load', () => {
	test('fills the list, marks ready and clears the error', async () => {
		companies.mockResolvedValue([co('a'), co('b')]);
		const c = new Companies();
		expect(c.ready).toBe(false);
		await c.load();
		expect(c.list.map((x) => x.slug)).toEqual(['a', 'b']);
		expect(c.ready).toBe(true);
		expect(c.error).toBeNull();
	});

	test('sets error instead of throwing, and stays not ready', async () => {
		companies.mockRejectedValue(new TypeError('Failed to fetch'));
		const c = new Companies();
		await expect(c.load()).resolves.toBeUndefined();
		expect(c.error).toBe('Failed to fetch');
		expect(c.ready).toBe(false);
		expect(c.list).toEqual([]);
	});

	test('a failed reload keeps the list already shown; a later success clears the error', async () => {
		const c = new Companies();
		companies.mockResolvedValueOnce([co('a')]);
		await c.load();
		companies.mockRejectedValueOnce(new Error('down'));
		await c.load();
		expect(c.error).toBe('down');
		expect(c.list.map((x) => x.slug)).toEqual(['a']);
		companies.mockResolvedValueOnce([co('a'), co('b')]);
		await c.load();
		expect(c.error).toBeNull();
		expect(c.list).toHaveLength(2);
	});

	test('a status event that arrives while the list loads is not lost', async () => {
		let resolve!: (list: Company[]) => void;
		companies.mockReturnValue(new Promise((r) => (resolve = r)));
		const c = new Companies();
		const loading = c.load();
		c.apply(co('a', 'building'));
		resolve([co('a', 'ready'), co('b')]);
		await loading;
		expect(c.list.map((x) => `${x.slug}:${x.status}`)).toEqual(['a:building', 'b:ready']);
	});

	test('of two overlapping loads the later one wins', async () => {
		const resolvers: ((list: Company[]) => void)[] = [];
		companies.mockImplementation(() => new Promise((r) => resolvers.push(r)));
		const c = new Companies();
		const first = c.load();
		const second = c.load();
		resolvers[1]([co('new')]);
		await second;
		resolvers[0]([co('old')]);
		await first;
		expect(c.list.map((x) => x.slug)).toEqual(['new']);
	});
});

describe('start', () => {
	test('loads, subscribes to /api/events and applies status events', async () => {
		companies.mockResolvedValue([co('a')]);
		const close = vi.fn();
		events.mockReturnValue(close);
		const c = new Companies();
		const stop = c.start();
		expect(events).toHaveBeenCalledTimes(1);
		const [path, handlers, opts] = events.mock.calls[0];
		expect(path).toBe('/api/events');
		await vi.waitFor(() => expect(c.ready).toBe(true));

		handlers.status(co('a', 'building'));
		expect(c.byslug('a')?.status).toBe('building');

		// every open (first connect and reconnects) re-reads the list
		companies.mockClear();
		opts?.onOpen?.();
		expect(companies).toHaveBeenCalledTimes(1);

		stop();
		expect(close).toHaveBeenCalledTimes(1);
	});
});
