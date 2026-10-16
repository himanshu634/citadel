import { afterEach, describe, expect, test, vi } from 'vitest';
import { Chats } from './chats.svelte';
import type { ThreadSummary } from './types';

afterEach(() => vi.unstubAllGlobals());

const chat = (id: string, minute: number): ThreadSummary => ({
	id,
	title: `Q ${id}`,
	created_at: `2026-10-16T10:${String(minute).padStart(2, '0')}:00Z`,
	updated_at: `2026-10-16T10:${String(minute).padStart(2, '0')}:00Z`,
	turns: 1,
	last_status: 'done'
});

function answer(...responses: [number, unknown][]) {
	const fetchMock = vi.fn(async () => {
		const [status, body] = responses.shift() ?? [200, {}];
		return new Response(status === 204 ? null : JSON.stringify(body), { status });
	});
	vi.stubGlobal('fetch', fetchMock);
	return fetchMock;
}

describe('Chats', () => {
	test('pages on with `before`, and a refresh keeps the older pages', async () => {
		const fetchMock = answer(
			[200, { threads: [chat('c', 3), chat('b', 2)], next: 2 }],
			[200, { threads: [chat('a', 1)], next: null }],
			[200, { threads: [chat('d', 4), chat('c', 3)], next: 3 }]
		);
		const chats = new Chats('acme');
		await chats.refresh();
		await chats.more();
		expect((fetchMock.mock.calls[1] as unknown as [string])[0]).toBe('/api/companies/acme/threads?before=2');
		expect(chats.threads.map((t) => t.id)).toEqual(['c', 'b', 'a']);
		expect(chats.next).toBeNull();
		await chats.refresh();
		expect(chats.threads.map((t) => t.id)).toEqual(['d', 'c', 'b', 'a']);
		expect(chats.next).toBeNull();
	});

	test('delete drops the chat; a refused delete says why and keeps it', async () => {
		answer(
			[200, { threads: [chat('b', 2), chat('a', 1)], next: null }],
			[204, null],
			[409, { detail: 'This chat is still answering. Stop it first.' }]
		);
		const chats = new Chats('acme');
		await chats.refresh();
		expect(await chats.remove('a')).toBe(true);
		expect(chats.threads.map((t) => t.id)).toEqual(['b']);
		expect(await chats.remove('b')).toBe(false);
		expect(chats.error).toMatch(/still answering/);
		expect(chats.threads.map((t) => t.id)).toEqual(['b']);
	});

	test('a failed read says why', async () => {
		answer([503, { detail: 'FalkorDB is not reachable' }]);
		const chats = new Chats('acme');
		await chats.refresh();
		expect(chats.error).toBe('FalkorDB is not reachable');
		expect(chats.loading).toBe(false);
	});
});
