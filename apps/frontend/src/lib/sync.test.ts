import { afterEach, expect, test, vi } from 'vitest';
import { startSync } from './sync';

function reply(status: number, body?: unknown) {
	const fetchMock = vi.fn(
		async () => new Response(body === undefined ? null : JSON.stringify(body), { status })
	);
	vi.stubGlobal('fetch', fetchMock);
	return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

test('starts an incremental build for the company', async () => {
	const fetchMock = reply(202, { slug: 'acme' });
	expect(await startSync('acme')).toEqual({ kind: 'started' });
	expect(fetchMock).toHaveBeenCalledWith(
		'/api/companies/acme/builds',
		expect.objectContaining({ method: 'POST', body: JSON.stringify({ full: false }) })
	);
});

test('a 409 means a build is already running, not a failure', async () => {
	reply(409, { detail: 'A build is running for acme' });
	expect(await startSync('acme')).toEqual({ kind: 'running' });
});

test('any other failure comes back as a sentence', async () => {
	reply(404, { detail: 'No company acme' });
	expect(await startSync('acme')).toEqual({ kind: 'failed', message: 'No company acme' });
	vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))));
	expect(await startSync('acme')).toEqual({
		kind: 'failed',
		message: "The Citadel API isn't answering. Start it with make api, then try again."
	});
});
