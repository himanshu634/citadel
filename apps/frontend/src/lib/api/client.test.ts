import { afterEach, describe, expect, test, vi } from 'vitest';
import { api, ApiError, describeError, rebuildRequired } from './client';

function reply(status: number, body?: unknown) {
	const fetchMock = vi.fn(
		async () => new Response(body === undefined ? null : JSON.stringify(body), { status })
	);
	vi.stubGlobal('fetch', fetchMock);
	return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe('api', () => {
	test('calls /api relative to the page', async () => {
		const fetchMock = reply(200, []);
		await api.companies();
		expect(fetchMock).toHaveBeenCalledWith('/api/companies', expect.objectContaining({ method: 'GET' }));
	});

	test('update sends the query flags the backend reads', async () => {
		const fetchMock = reply(200, {});
		await api.update('acme', { slug: 'acme' } as never, { dryRun: true });
		expect(fetchMock.mock.calls[0]).toEqual([
			'/api/companies/acme?dry_run=1',
			expect.objectContaining({ method: 'PUT', body: JSON.stringify({ slug: 'acme' }) })
		]);
		await api.update('acme', { slug: 'acme' } as never, { rebuild: true });
		expect((fetchMock.mock.calls[1] as unknown[])[0]).toBe('/api/companies/acme?rebuild=1');
		await api.update('acme', { slug: 'acme' } as never);
		expect((fetchMock.mock.calls[2] as unknown[])[0]).toBe('/api/companies/acme');
	});

	test('startBuild sends full, stopBuild deletes the current build', async () => {
		const fetchMock = reply(202, {});
		await api.startBuild('acme', true);
		expect(fetchMock.mock.calls[0]).toEqual([
			'/api/companies/acme/builds',
			expect.objectContaining({ method: 'POST', body: JSON.stringify({ full: true }) })
		]);
		await api.stopBuild('acme');
		expect(fetchMock.mock.calls[1]).toEqual([
			'/api/companies/acme/builds/current',
			expect.objectContaining({ method: 'DELETE' })
		]);
	});

	test('githubRepo escapes the path parts', async () => {
		const fetchMock = reply(200, { exists: true, private: false });
		await api.githubRepo('FalkorDB', 'a b');
		expect((fetchMock.mock.calls[0] as unknown[])[0]).toBe('/api/checks/github/FalkorDB/a%20b');
	});

	test('a non-2xx answer throws ApiError with status and detail', async () => {
		reply(409, { detail: 'acme is already a company. Pick another name' });
		const err = await api.create({ slug: 'acme' } as never).catch((e) => e);
		expect(err).toBeInstanceOf(ApiError);
		expect(err.status).toBe(409);
		expect(err.detail).toBe('acme is already a company. Pick another name');
	});

	test('a non-JSON error body still throws ApiError', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => new Response('Bad gateway', { status: 502 })));
		const err = await api.companies().catch((e) => e);
		expect(err).toBeInstanceOf(ApiError);
		expect(err.status).toBe(502);
		expect(err.detail).toBe('Bad gateway');
	});
});

test('rebuildRequired reads the 409 detail of a Settings save', () => {
	const change = { slug: 'acme', changed: true, rebuild: true, refetch: [], reasons: ['x'] };
	expect(rebuildRequired(new ApiError(409, { rebuild_required: change }))).toEqual(change);
	expect(rebuildRequired(new ApiError(409, 'A build for acme is already running'))).toBeNull();
	expect(rebuildRequired(new Error('x'))).toBeNull();
});

describe('describeError', () => {
	const down = "The Citadel API isn't answering. Start it with make api, then try again.";

	test("the API's own sentence wins", () => {
		expect(describeError(new ApiError(409, 'acme is already a company. Pick another name'))).toBe(
			'acme is already a company. Pick another name'
		);
		expect(describeError(new ApiError(500, 'Something broke'))).toBe('Something broke');
	});

	test('503 without a sentence means FalkorDB is down', () => {
		expect(describeError(new ApiError(503, undefined))).toBe(
			"FalkorDB isn't answering. Start it with make up, then try again."
		);
	});

	test('a 4xx without a sentence is a refusal', () => {
		expect(describeError(new ApiError(422, [{ loc: ['name'], msg: 'x' }]))).toBe(
			'The API refused the request (422).'
		);
	});

	test('a network failure or a bodyless proxy 500 means the API is not answering', () => {
		expect(describeError(new TypeError('Failed to fetch'))).toBe(down);
		expect(describeError(new ApiError(500, undefined))).toBe(down);
		expect(describeError(new ApiError(502, ''))).toBe(down);
		expect(describeError('odd')).toBe(down);
	});
});
