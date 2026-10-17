import { describe, expect, test } from 'vitest';
import { ApiError } from './api/client';
import {
	changedSections,
	classifySaveError,
	isDirty,
	rebuildDialog,
	saveCost,
	settingsReason,
	syncLine,
	unsavedLine
} from './settings';
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
		const down = "The Citadel API isn't answering. Start it with make api, then try again.";
		expect(classifySaveError(new TypeError('Failed to fetch'))).toEqual({
			kind: 'other',
			message: down
		});
		expect(classifySaveError('odd')).toEqual({ kind: 'other', message: down });
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

describe('settingsReason', () => {
	test('drops the wizard step wording and names the tab to go to', () => {
		expect(settingsReason(null)).toBeNull();
		expect(settingsReason('Checking')).toEqual({ text: 'Checking', section: null });
		expect(settingsReason('Checking GitHub')).toEqual({ text: 'Checking GitHub', section: null });
		expect(settingsReason('Fix the fields marked above.')).toEqual({
			text: 'Fix the fields marked in Systems and people.',
			section: 'rules'
		});
		expect(settingsReason('Fix the errors in Sources (step 2) first.')).toEqual({
			text: 'Fix the fields marked in Sources.',
			section: 'sources'
		});
		expect(settingsReason('Company (step 1): Enter the company name to continue.')).toEqual({
			text: 'Enter the company name to save.',
			section: 'company'
		});
		expect(settingsReason('Sources (step 2): Add at least one source to continue.')).toEqual({
			text: 'Add at least one source to save.',
			section: 'sources'
		});
		expect(settingsReason('Enter the company name to continue.')).toEqual({
			text: 'Enter the company name to save.',
			section: null
		});
	});
});

describe('changedSections', () => {
	test('is empty for an untouched copy', () => {
		expect(changedSections(config(), config())).toEqual([]);
	});

	test('names each tab whose part of the file changed, in tab order', () => {
		const draft = config({
			people: { bots: ['ci-bot', 'renovate[bot]'], aliases: {} },
			name: 'Acme'
		});
		expect(changedSections(draft, config())).toEqual(['company', 'rules']);
	});

	test('ignores what cleaning removes', () => {
		const draft = config({ name: ' Acme Labs  ' });
		draft.systems!.rules!.push({ match: '', system: '' });
		expect(changedSections(draft, config())).toEqual([]);
	});

	test('a removed source is a Sources change', () => {
		expect(changedSections(config({ sources: [] }), config())).toEqual(['sources']);
	});
});

describe('unsavedLine', () => {
	test('lists the tabs as a sentence', () => {
		expect(unsavedLine([])).toBe('Unsaved changes.');
		expect(unsavedLine(['sources'])).toBe('Unsaved changes in Sources.');
		expect(unsavedLine(['company', 'rules'])).toBe(
			'Unsaved changes in Company and Systems and people.'
		);
		expect(unsavedLine(['company', 'sources', 'rules'])).toBe(
			'Unsaved changes in Company, Sources and Systems and people.'
		);
	});
});

describe('saveCost', () => {
	test('is unknown without a dry run or a change', () => {
		expect(saveCost(null)).toBeNull();
		expect(saveCost(change({ changed: false, rebuild: false }))).toBeNull();
	});

	test('a change that touches nothing saves plainly', () => {
		expect(saveCost(change({ rebuild: false }))).toEqual({
			label: 'Save',
			rebuild: false,
			line: 'Saves at once. The graph is not touched.'
		});
	});

	test('an added source starts a build without a rebuild', () => {
		expect(saveCost(change({ rebuild: false, refetch: ['github:acme/web'] }))?.line).toBe(
			'Saving starts a build to download github:acme/web.'
		);
	});

	test('a rebuild names itself on the button', () => {
		expect(saveCost(change())).toEqual({
			label: 'Save and rebuild',
			rebuild: true,
			line: 'Saving rebuilds the graph from the data already downloaded.'
		});
		expect(saveCost(change({ refetch: ['github:acme/platform'] }))?.line).toBe(
			'Saving downloads github:acme/platform again and rebuilds the graph.'
		);
	});
});
