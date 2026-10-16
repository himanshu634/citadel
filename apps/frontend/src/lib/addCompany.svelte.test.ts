import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

vi.mock('./api/client', async () => {
	class ApiError extends Error {
		constructor(
			readonly status: number,
			readonly detail: unknown
		) {
			super(String(detail));
		}
	}
	return {
		ApiError,
		api: { lookupRepo: vi.fn(), onboard: vi.fn(), company: vi.fn(), update: vi.fn() },
		describeError: (e: unknown) => (e instanceof Error ? e.message : 'down')
	};
});

import { ApiError, api } from './api/client';
import { AddCompany } from './addCompany.svelte';
import type { RepoLookup } from './types';

const lookupRepo = vi.mocked(api.lookupRepo);
const onboard = vi.mocked(api.onboard);
const company = vi.mocked(api.company);
const update = vi.mocked(api.update);

function found(over: Partial<RepoLookup> = {}): RepoLookup {
	return {
		repo: 'acme-labs/platform',
		exists: true,
		private: false,
		owner_name: 'Acme Labs',
		name: 'Acme Labs',
		slug: 'acme_labs',
		since: '2025-10-16',
		company: null,
		owner_company: null,
		...over
	};
}

/** Type `text` and let the lookup run. */
async function typed(add: AddCompany, text: string) {
	add.input(text);
	await vi.advanceTimersByTimeAsync(300);
}

beforeEach(() => {
	vi.useFakeTimers();
	for (const m of [lookupRepo, onboard, company, update]) m.mockReset();
});
afterEach(() => vi.useRealTimers());

describe('the field', () => {
	test('empty, then typing until it is owner/name', () => {
		const add = new AddCompany();
		expect(add.view).toBe('empty');
		add.input('acme-labs');
		expect(add.view).toBe('typing');
		expect(lookupRepo).not.toHaveBeenCalled();
	});

	test('a pasted link is looked up once typing pauses', async () => {
		lookupRepo.mockResolvedValue(found());
		const add = new AddCompany();
		add.input('https://github.com/acme-labs/platform/tree/main');
		expect(add.view).toBe('checking');
		await vi.advanceTimersByTimeAsync(300);
		expect(lookupRepo).toHaveBeenCalledExactlyOnceWith('acme-labs', 'platform');
		expect(add.view).toBe('ready');
		expect(add.companyName).toBe('Acme Labs');
		expect(add.canCreate).toBe(true);
	});

	test('an answer for older text is dropped', async () => {
		let answer!: (v: RepoLookup) => void;
		lookupRepo.mockImplementationOnce(() => new Promise((r) => (answer = r)));
		lookupRepo.mockResolvedValueOnce(found({ repo: 'acme-labs/web', name: 'Acme Labs web' }));
		const add = new AddCompany();
		await typed(add, 'acme-labs/platform');
		await typed(add, 'acme-labs/web');
		answer(found());
		await vi.runAllTimersAsync();
		expect(add.found?.repo).toBe('acme-labs/web');
	});
});

describe('what the lookup says', () => {
	test.each([
		[{ exists: false, private: null }, 'missing'],
		[{ private: true }, 'private'],
		[{ company: { slug: 'acme_labs', name: 'Acme Labs' } }, 'taken'],
		[{ owner_company: { slug: 'acme_labs', name: 'Acme Labs' } }, 'owner']
	] as const)('%o -> %s', async (over, view) => {
		lookupRepo.mockResolvedValue(found(over));
		const add = new AddCompany();
		await typed(add, 'acme-labs/platform');
		expect(add.view).toBe(view);
		expect(add.canCreate).toBe(view === 'owner');
	});

	test.each([
		[424, 'no_token'],
		[429, 'rate_limited'],
		[502, 'unreachable']
	] as const)('HTTP %i -> %s, and Check again asks again', async (status, view) => {
		lookupRepo.mockRejectedValueOnce(new ApiError(status, 'x'));
		const add = new AddCompany();
		await typed(add, 'acme-labs/platform');
		expect(add.view).toBe(view);
		lookupRepo.mockResolvedValueOnce(found());
		await add.retry();
		expect(add.view).toBe('ready');
	});
});

describe('create', () => {
	test('sends the repo and slug, and an edited name only', async () => {
		lookupRepo.mockResolvedValue(found());
		onboard.mockResolvedValue({
			company: { slug: 'acme_labs' } as never,
			build: null,
			build_error: null
		});
		const add = new AddCompany();
		await typed(add, 'acme-labs/platform');
		expect(await add.create()).toBe('acme_labs');
		expect(onboard).toHaveBeenLastCalledWith({ repo: 'acme-labs/platform', slug: 'acme_labs' });
		add.name = 'Acme';
		await add.create();
		expect(onboard).toHaveBeenLastCalledWith({
			repo: 'acme-labs/platform',
			slug: 'acme_labs',
			name: 'Acme'
		});
	});

	test('a repo found private on create turns into the private state', async () => {
		lookupRepo.mockResolvedValue(found());
		onboard.mockRejectedValue(new ApiError(422, { code: 'private_repo', message: 'no' }));
		const add = new AddCompany();
		await typed(add, 'acme-labs/platform');
		expect(await add.create()).toBeNull();
		expect(add.view).toBe('private');
	});

	test('a repo another company took meanwhile shows that company', async () => {
		lookupRepo.mockResolvedValue(found());
		const detail = { code: 'repo_taken', slug: 'acme', name: 'Acme' };
		onboard.mockRejectedValue(new ApiError(409, detail));
		const add = new AddCompany();
		await typed(add, 'acme-labs/platform');
		await add.create();
		expect(add.view).toBe('taken');
		expect(add.found?.company).toEqual({ slug: 'acme', name: 'Acme' });
	});

	test('field errors and other failures are said in one line', async () => {
		lookupRepo.mockResolvedValue(found());
		onboard.mockRejectedValueOnce(new ApiError(422, [{ loc: ['name'], msg: 'Field required' }]));
		const add = new AddCompany();
		await typed(add, 'acme-labs/platform');
		await add.create();
		expect(add.error).toBe('Field required');
		onboard.mockRejectedValueOnce(new Error('offline'));
		await add.create();
		expect(add.error).toBe('offline');
		expect(add.busy).toBe(false);
	});
});

test('addTo appends the repo as a github source of that company', async () => {
	lookupRepo.mockResolvedValue(found({ owner_company: { slug: 'acme', name: 'Acme' } }));
	const config = { slug: 'acme', sources: [{ type: 'github', repo: 'acme-labs/web' }] };
	company.mockResolvedValue({ config } as never);
	update.mockResolvedValue({} as never);
	const add = new AddCompany();
	await typed(add, 'acme-labs/platform');
	expect(await add.addTo('acme')).toBe('acme');
	const [slug, cfg] = update.mock.calls[0];
	expect(slug).toBe('acme');
	expect(cfg.sources.map((s) => s.repo)).toEqual(['acme-labs/web', 'acme-labs/platform']);
});

test('show starts from an empty field', async () => {
	lookupRepo.mockResolvedValue(found());
	const add = new AddCompany();
	await typed(add, 'acme-labs/platform');
	add.name = 'X';
	add.show();
	expect(add.open).toBe(true);
	expect(add.view).toBe('empty');
	expect(add.name).toBeNull();
});
