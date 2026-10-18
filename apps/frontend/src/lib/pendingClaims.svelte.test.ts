import { afterEach, describe, expect, test, vi } from 'vitest';
import { PendingClaims } from './pendingClaims.svelte';
import type { Claim } from './types';

const claim = (uid: string): Claim =>
	({
		uid,
		kind: 'expert',
		subject: 'system:Billing',
		statement: `${uid} is a claim.`,
		value: null,
		about: [],
		evidence: [],
		status: 'pending_approval',
		critical: true,
		critical_reasons: ['high_impact_system'],
		conflict: null,
		valid_from: null,
		valid_to: null
	}) as unknown as Claim;

function serve(status: number, body: unknown) {
	const fetch = vi.fn(async () => new Response(JSON.stringify(body), { status }));
	vi.stubGlobal('fetch', fetch);
	return fetch;
}

afterEach(() => {
	vi.unstubAllGlobals();
	vi.useRealTimers();
});

describe('PendingClaims', () => {
	test('follows a company: counts its waiting claims and knows their uids', async () => {
		const fetch = serve(200, [claim('claim:a'), claim('claim:b')]);
		const pending = new PendingClaims();
		const stop = pending.follow('acme');
		await vi.waitFor(() => expect(pending.count('acme')).toBe(2));
		expect(String((fetch.mock.calls[0] as unknown[])[0])).toContain('/companies/acme/keeper/claims?status=pending_approval');
		expect(pending.uids('acme')).toEqual(new Set(['claim:a', 'claim:b']));
		expect(pending.count('other')).toBeNull();
		stop();
	});

	test('a failed read shows no count rather than an error', async () => {
		serve(409, { detail: 'acme is being rebuilt' });
		const pending = new PendingClaims();
		await pending.refresh('acme');
		expect(pending.count('acme')).toBeNull();
	});

	test("drops an answer for a company the user has left", async () => {
		let answer!: (r: Response) => void;
		vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((done) => (answer = done))));
		const pending = new PendingClaims();
		const stop = pending.follow('acme');
		stop();
		pending.follow('globex');
		answer(new Response(JSON.stringify([claim('claim:a')]), { status: 200 }));
		await Promise.resolve();
		expect(pending.count('acme')).toBeNull();
		expect(pending.slug).toBe('globex');
	});

	test('reads again on its timer until stopped', async () => {
		vi.useFakeTimers();
		const fetch = serve(200, []);
		const pending = new PendingClaims();
		const stop = pending.follow('acme');
		await vi.advanceTimersByTimeAsync(0);
		expect(fetch).toHaveBeenCalledTimes(1);
		await vi.advanceTimersByTimeAsync(20_000);
		expect(fetch).toHaveBeenCalledTimes(2);
		stop();
		await vi.advanceTimersByTimeAsync(60_000);
		expect(fetch).toHaveBeenCalledTimes(2);
	});
});
