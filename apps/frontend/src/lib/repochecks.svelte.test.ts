import { beforeEach, describe, expect, test, vi } from 'vitest';

vi.mock('./api/client', async () => {
	class ApiError extends Error {
		constructor(
			readonly status: number,
			readonly detail: unknown
		) {
			super(String(detail));
		}
	}
	return { ApiError, api: { githubToken: vi.fn(), githubRepo: vi.fn() } };
});

import { ApiError, api } from './api/client';
import { RepoChecks } from './repochecks.svelte';

const token = vi.mocked(api.githubToken);
const repo = vi.mocked(api.githubRepo);

beforeEach(() => {
	token.mockReset();
	repo.mockReset();
});

describe('checkToken', () => {
	test('records where the token comes from, or null when there is none', async () => {
		const checks = new RepoChecks();
		expect(checks.token).toBeUndefined();
		token.mockResolvedValue({ token: 'gh' });
		await checks.checkToken();
		expect(checks.token).toBe('gh');
		token.mockResolvedValue({ token: null });
		await checks.checkToken();
		expect(checks.token).toBeNull();
	});

	test('an unreachable API leaves the token unknown, not missing', async () => {
		const checks = new RepoChecks();
		token.mockRejectedValue(new Error('offline'));
		await checks.checkToken();
		expect(checks.token).toBeUndefined();
	});
});

describe('check', () => {
	test('stores a public and a private repository', async () => {
		const checks = new RepoChecks();
		repo.mockResolvedValueOnce({ exists: true, private: false });
		repo.mockResolvedValueOnce({ exists: true, private: true });
		await checks.check('a/open');
		await checks.check('a/secret');
		expect(repo).toHaveBeenCalledWith('a', 'open');
		expect(checks.results.get('a/open')).toEqual({ kind: 'found', private: false });
		expect(checks.fact('a/secret')).toBe('private');
		expect(checks.fact('a/open')).toBeUndefined();
		expect(checks.fact('a/unknown')).toBeUndefined();
	});

	test('a missing repository is its own result', async () => {
		const checks = new RepoChecks();
		repo.mockResolvedValue({ exists: false, private: null });
		await checks.check('a/gone');
		expect(checks.results.get('a/gone')).toEqual({ kind: 'missing' });
		expect(checks.fact('a/gone')).toBe('missing');
	});

	test('maps 424, 429 and 502 and anything else to a result that does not block', async () => {
		const checks = new RepoChecks();
		const cases: [unknown, string][] = [
			[new ApiError(424, 'no token'), 'no_token'],
			[new ApiError(429, 'slow down'), 'rate_limited'],
			[new ApiError(502, 'github'), 'unreachable'],
			[new Error('offline'), 'unreachable']
		];
		for (const [error, kind] of cases) {
			repo.mockRejectedValueOnce(error);
			await checks.check('a/b', true);
			expect(checks.results.get('a/b')).toEqual({ kind });
		}
		expect(checks.fact('a/b')).toBeUndefined();
	});

	test('does not ask twice about a repository it has an answer for, unless forced', async () => {
		const checks = new RepoChecks();
		repo.mockResolvedValue({ exists: true, private: false });
		await checks.check('a/b');
		await checks.check('a/b');
		expect(repo).toHaveBeenCalledTimes(1);
		await checks.check('a/b', true);
		expect(repo).toHaveBeenCalledTimes(2);
	});

	test('asks again after a failure that may pass', async () => {
		const checks = new RepoChecks();
		repo.mockRejectedValueOnce(new ApiError(429, 'slow down'));
		repo.mockResolvedValueOnce({ exists: true, private: false });
		await checks.check('a/b');
		await checks.check('a/b');
		expect(checks.results.get('a/b')).toEqual({ kind: 'found', private: false });
	});

	test('joins a check already in flight', async () => {
		const checks = new RepoChecks();
		let finish: (v: { exists: boolean; private: boolean }) => void = () => {};
		repo.mockReturnValue(new Promise((resolve) => (finish = resolve)));
		const first = checks.check('a/b');
		const second = checks.check('a/b');
		expect(checks.checking.has('a/b')).toBe(true);
		finish({ exists: true, private: false });
		await Promise.all([first, second]);
		expect(repo).toHaveBeenCalledTimes(1);
		expect(checks.checking.has('a/b')).toBe(false);
	});

	test('ignores text that is not owner/name', async () => {
		const checks = new RepoChecks();
		await checks.check('nonsense');
		expect(repo).not.toHaveBeenCalled();
	});
});
