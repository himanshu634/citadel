import { describe, expect, test } from 'vitest';
import { ApiError } from './api/client';
import { classifySaveError, isDirty, rebuildDialog, syncLine } from './settings';
import type { CompanyConfig, ConfigChange } from './types';

function config(over: Partial<CompanyConfig> = {}): CompanyConfig {
	return {
		slug: 'acme',
		name: 'Acme Labs',
		data_permission: 'public',
		window: { since: '2026-01-01' },
		sources: [{ type: 'github', repo: 'acme/platform', include: ['commits', 'issues'] }],
		systems: { rules: [{ match: 'web/**', system: 'Web' }], fallback: 'depth_1', ignore: [] },
		people: { bots: ['ci-bot'], aliases: {} },
		...over
	};
}

function change(over: Partial<ConfigChange> = {}): ConfigChange {
	return { slug: 'acme', changed: true, rebuild: true, refetch: [], reasons: [], ...over };
}

describe('isDirty', () => {
	test('is false for an untouched copy', () => {
		expect(isDirty(config(), config())).toBe(false);
	});

	test('ignores key order, surrounding spaces and empty rule rows', () => {
		const loaded = config();
		const draft = config({
			name: '  Acme Labs ',
			systems: {
				ignore: [' '],
				fallback: 'depth_1',
				rules: [
					{ system: 'Web', match: 'web/**' },
					{ match: '', system: '' }
				]
			}
		});
		expect(isDirty(draft, loaded)).toBe(false);
	});

	test('treats a missing systems or people block as the empty one the form adds', () => {
		const loaded = config({ systems: undefined, people: undefined });
		const draft = config({
			systems: { rules: [], fallback: 'depth_2', ignore: [] },
			people: { bots: [], aliases: {} }
		});
		expect(isDirty(draft, loaded)).toBe(false);
	});

	test('is true for a changed name, date, rule, source or alias', () => {
		expect(isDirty(config({ name: 'Acme' }), config())).toBe(true);
		expect(isDirty(config({ window: { since: '2025-01-01' } }), config())).toBe(true);
		expect(
			isDirty(config({ systems: { rules: [], fallback: 'depth_1', ignore: [] } }), config())
		).toBe(true);
		expect(isDirty(config({ sources: [] }), config())).toBe(true);
		expect(isDirty(config({ people: { bots: ['ci-bot'], aliases: { a: 'b' } } }), config())).toBe(
			true
		);
	});

	test('does not count a name that only changed in trailing whitespace', () => {
		expect(isDirty(config({ name: 'Acme Labs  ' }), config())).toBe(false);
	});
});

describe('rebuildDialog', () => {
	test('titles it with the company name and lists the reasons', () => {
		const d = rebuildDialog('Acme Labs', change({ reasons: ['The start date moved'] }));
		expect(d.title).toBe("Rebuild Acme Labs' graph?");
		expect(d.reasons).toEqual(['The start date moved']);
		expect(d.explanation).toBe(
			'The graph is emptied and rebuilt from the cached data. Answers are unavailable until it finishes.'
		);
		expect(d.refetch).toBeNull();
	});

	test('a name ending in s gets only the apostrophe, others get apostrophe s', () => {
		expect(rebuildDialog('Acme Labs', change()).title).toBe("Rebuild Acme Labs' graph?");
		expect(rebuildDialog('Acme', change()).title).toBe("Rebuild Acme's graph?");
	});

	test('names the sources that are downloaded again', () => {
		const d = rebuildDialog('Acme', change({ refetch: ['github:acme/a', 'github:acme/b'] }));
		expect(d.refetch).toBe('These sources are downloaded again: github:acme/a, github:acme/b');
	});
});

describe('classifySaveError', () => {
	test('a 409 with rebuild_required carries the change', () => {
		const c = change({ reasons: ['x'] });
		const e = new ApiError(409, { rebuild_required: c });
		expect(classifySaveError(e)).toEqual({ kind: 'rebuild', change: c });
	});

	test('a 409 with a string means a build is running', () => {
		const e = new ApiError(409, 'A build for acme is already running');
		expect(classifySaveError(e)).toEqual({ kind: 'running' });
	});

	test('a 422 with a list keeps the field errors', () => {
		const errors = [{ loc: ['window', 'since'], msg: 'bad' }];
		expect(classifySaveError(new ApiError(422, errors))).toEqual({ kind: 'invalid', errors });
	});

	test('anything else is a message', () => {
		expect(classifySaveError(new ApiError(500, 'boom'))).toEqual({ kind: 'other', message: 'boom' });
		expect(classifySaveError(new Error('offline'))).toEqual({ kind: 'other', message: 'offline' });
		expect(classifySaveError('odd')).toEqual({ kind: 'other', message: 'odd' });
	});
});

describe('syncLine', () => {
	test('says what was saved, and that a build started when sources are fetched', () => {
		expect(syncLine([])).toBe('Saved');
		expect(syncLine(['github:acme/new'])).toBe(
			'Saved. A build started to download github:acme/new.'
		);
	});
});
