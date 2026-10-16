import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { MODEL_KEY, ModelChoice } from './models.svelte';
import type { ModelsOut } from './types';

const LIST: ModelsOut = {
	models: [
		{ id: 'claude-haiku-5-5', name: 'Haiku 5.5', blurb: 'Fastest.', cost: 1, slow: false },
		{ id: 'claude-opus-5-5', name: 'Opus 5.5', blurb: 'Careful.', cost: 40, slow: false },
		{ id: 'claude-fable-5-1', name: 'Fable 5.1', blurb: 'Slow.', cost: 100, slow: true }
	],
	default: 'claude-haiku-5-5'
};

function serve(status: number, body: unknown) {
	vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(body), { status })));
}

// The tests run in node: a Map stands in for the browser's storage.
beforeEach(() => {
	const items = new Map<string, string>();
	vi.stubGlobal('localStorage', {
		getItem: (k: string) => items.get(k) ?? null,
		setItem: (k: string, v: string) => void items.set(k, v)
	});
});
afterEach(() => vi.unstubAllGlobals());

describe('ModelChoice', () => {
	test('starts on the default, and a pick is remembered for the next visit', async () => {
		serve(200, LIST);
		const first = new ModelChoice();
		await first.load();
		expect(first.selected).toBe('claude-haiku-5-5');
		first.pick('claude-opus-5-5');
		expect(first.current?.name).toBe('Opus 5.5');
		expect(localStorage.getItem(MODEL_KEY)).toBe('claude-opus-5-5');

		const next = new ModelChoice();
		await next.load();
		expect(next.selected).toBe('claude-opus-5-5');
	});

	test('a remembered model the server no longer offers falls back to the default', async () => {
		localStorage.setItem(MODEL_KEY, 'claude-opus-4-1');
		serve(200, LIST);
		const c = new ModelChoice();
		await c.load();
		expect(c.selected).toBe('claude-haiku-5-5');
	});

	test('an unknown pick is ignored; a failed load leaves nothing picked', async () => {
		serve(200, LIST);
		const c = new ModelChoice();
		await c.load();
		c.pick('gpt-5');
		expect(c.selected).toBe('claude-haiku-5-5');

		serve(500, { detail: 'down' });
		const down = new ModelChoice();
		await down.load();
		expect(down.selected).toBeNull();
		expect(down.models).toEqual([]);
	});

	test('names a model by id, and keeps an id it does not know (a fallback model)', async () => {
		serve(200, LIST);
		const c = new ModelChoice();
		await c.load();
		expect(c.nameOf('claude-fable-5-1')).toBe('Fable 5.1');
		expect(c.nameOf('claude-opus-4-8')).toBe('claude-opus-4-8');
		expect(c.nameOf(null)).toBeNull();
	});
});
