import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import {
	SECTION_KEYS,
	GITHUB_PARTS,
	aliasRowsToRecord,
	blankSource,
	cleanDraft,
	debounce,
	defaultDraft,
	errorsIn,
	firstSectionWithErrors,
	friendly,
	incompleteReason,
	messageAt,
	normalizeRepo,
	parseRepo,
	repoErrorFor,
	repoErrors,
	PRIVATE_REPO_MESSAGE,
	LINEAR_ADD_REASON,
	LINEAR_PERMISSION_MESSAGE,
	SOURCE_KINDS,
	WORKSPACE_MESSAGE,
	addSourceBlocked,
	linearErrorFor,
	normalizeTeams,
	normalizeWorkspace,
	requiredField,
	sourceErrors,
	teamsMessage,
	workspaceMessage,
	continueGate,
	saveGate,
	visibleErrors,
	type Gate,
	recordToAliasRows,
	sectionOfLoc,
	splitYamlBlocks,
	unmatched
} from './onboarding';
import type { CompanyConfig, FieldError } from './types';

const err = (loc: (string | number)[], msg = 'bad'): FieldError => ({ loc, msg });

function draft(over: Partial<CompanyConfig> = {}): CompanyConfig {
	return {
		slug: 'acme',
		name: 'Acme',
		data_permission: 'public',
		window: { since: '2026-01-01' },
		sources: [{ type: 'canonical_jsonl', path: 'x' }],
		systems: { rules: [], fallback: 'depth_2', ignore: [] },
		people: { bots: [], aliases: {} },
		...over
	};
}

describe('sectionOfLoc', () => {
	test('maps each top-level key to the step that shows it', () => {
		expect(sectionOfLoc(['slug'])).toBe('company');
		expect(sectionOfLoc(['name'])).toBe('company');
		expect(sectionOfLoc(['data_permission'])).toBe('company');
		expect(sectionOfLoc(['window', 'since'])).toBe('company');
		expect(sectionOfLoc(['sources', 0, 'repo'])).toBe('sources');
		expect(sectionOfLoc(['systems', 'rules', 1, 'match'])).toBe('rules');
		expect(sectionOfLoc(['people', 'bots', 0])).toBe('rules');
	});

	test('an unknown or empty path belongs to no step', () => {
		expect(sectionOfLoc(['mystery'])).toBeNull();
		expect(sectionOfLoc([])).toBeNull();
	});

	test('SECTION_KEYS lists the keys each step adds to the file', () => {
		expect(SECTION_KEYS.company).toEqual(['slug', 'name', 'data_permission', 'window']);
		expect(SECTION_KEYS.sources).toEqual(['sources']);
		expect(SECTION_KEYS.rules).toEqual(['systems', 'people']);
	});
});

describe('errorsIn and firstSectionWithErrors', () => {
	const errors = [err(['sources', 0, 'repo']), err(['systems', 'fallback']), err(['mystery'])];

	test('errors of one step, with errors that match no step on the first', () => {
		expect(errorsIn(errors, 'sources')).toEqual([errors[0]]);
		expect(errorsIn(errors, 'rules')).toEqual([errors[1]]);
		expect(errorsIn(errors, 'company')).toEqual([errors[2]]);
	});

	test('the first step with an error, in step order', () => {
		expect(firstSectionWithErrors([err(['people', 'bots']), err(['sources', 0, 'repo'])])).toBe(1);
		expect(firstSectionWithErrors([err(['slug'])])).toBe(0);
		expect(firstSectionWithErrors([])).toBe(-1);
	});
});

describe('friendly', () => {
	test('a bad slug gets the spec wording', () => {
		const pattern = err(['slug'], "String should match pattern '^[a-z0-9][a-z0-9_]*$'");
		expect(friendly(pattern)).toBe(
			'Use lowercase letters, digits and underscores only, like acme_labs'
		);
	});

	test('the slug-taken sentence passes through verbatim', () => {
		const taken = err(['slug'], 'acme is already a company. Pick another name');
		expect(friendly(taken)).toBe('acme is already a company. Pick another name');
	});

	test('pydantic prefixes go and the sentence starts with a capital', () => {
		expect(friendly(err(['sources', 0, 'repo'], "Value error, repo must look like 'owner/name'"))).toBe(
			"Repo must look like 'owner/name'"
		);
	});
});

describe('messageAt and unmatched', () => {
	const errors = [
		err(['sources', 0, 'repo'], 'first'),
		err(['sources', 0, 'include', 2], 'in the list'),
		err(['sources', 1, 'path'], 'other card'),
		err(['sources', 0, 'type'], 'no field')
	];

	test('finds the message of the field whose path starts the error path', () => {
		expect(messageAt(errors, ['sources', 0, 'repo'])).toBe('First');
		expect(messageAt(errors, ['sources', 0, 'include'])).toBe('In the list');
		expect(messageAt(errors, ['sources', 2, 'repo'])).toBeUndefined();
	});

	test('does not mistake sources.1 for sources.10', () => {
		expect(messageAt([err(['sources', 10, 'repo'], 'ten')], ['sources', 1, 'repo'])).toBeUndefined();
	});

	test('joins several messages for one field', () => {
		const both = [err(['name'], 'one'), err(['name'], 'two')];
		expect(messageAt(both, ['name'])).toBe('One. Two');
	});

	test('one message is shown exactly as it came, including its last character', () => {
		const taken = [err(['slug'], 'acme is already a company. Pick another name')];
		expect(messageAt(taken, ['slug'])).toBe('acme is already a company. Pick another name');
		expect(messageAt([err(['name'], 'Ends with a stop.')], ['name'])).toBe('Ends with a stop.');
	});

	test('several messages keep their own stops', () => {
		const two = [err(['name'], 'one.'), err(['name'], 'two')];
		expect(messageAt(two, ['name'])).toBe('One. Two');
	});

	test('lists the errors no rendered field shows', () => {
		const shown = [['sources', 0, 'repo'], ['sources', 0, 'include'], ['sources', 1, 'path']];
		expect(unmatched(errors, shown)).toEqual([errors[3]]);
	});
});

describe('cleanDraft', () => {
	test('drops empty path rules and trims text', () => {
		const out = cleanDraft(
			draft({
				name: '  Acme  ',
				systems: {
					rules: [
						{ match: '', system: '' },
						{ match: ' web/** ', system: ' Web ' }
					],
					fallback: 'depth_2',
					ignore: []
				}
			})
		);
		expect(out.name).toBe('Acme');
		expect(out.systems?.rules).toEqual([{ match: 'web/**', system: 'Web' }]);
	});

	test('keeps a half-filled rule so validation and the blocker can see it', () => {
		const out = cleanDraft(
			draft({ systems: { rules: [{ match: 'web/**', system: '' }], fallback: 'none', ignore: [] } })
		);
		expect(out.systems?.rules).toEqual([{ match: 'web/**', system: '' }]);
	});

	test('trims source paths and repositories and does not change its input', () => {
		const input = draft({ sources: [{ type: 'github', repo: ' a/b ', include: ['commits'] }] });
		const out = cleanDraft(input);
		expect(out.sources[0]).toEqual({ type: 'github', repo: 'a/b', include: ['commits'] });
		expect((input.sources[0] as unknown as { repo: string }).repo).toBe(' a/b ');
	});
});

describe('incompleteReason', () => {
	test('company: a name is required', () => {
		expect(incompleteReason(draft({ name: '  ' }), 'company')).toBe('Enter the company name to continue.');
		expect(incompleteReason(draft(), 'company')).toBeNull();
	});

	test('sources: at least one, each with its repo or folder', () => {
		expect(incompleteReason(draft({ sources: [] }), 'sources')).toBe('Add at least one source to continue.');
		expect(incompleteReason(draft({ sources: [{ type: 'github', repo: '' }] }), 'sources')).toBe(
			'Fill in every source, or remove the ones you do not need.'
		);
		expect(incompleteReason(draft({ sources: [{ type: 'local_docs', path: ' ' }] }), 'sources')).toBe(
			'Fill in every source, or remove the ones you do not need.'
		);
		expect(incompleteReason(draft(), 'sources')).toBeNull();
	});

	test('rules: a rule needs both columns, an empty row is ignored', () => {
		const rules = [
			{ match: '', system: '' },
			{ match: 'a/**', system: '' }
		];
		expect(
			incompleteReason(draft({ systems: { rules, fallback: 'depth_2', ignore: [] } }), 'rules')
		).toBe('Give each path rule a pattern and a system, or remove the row.');
		expect(incompleteReason(draft(), 'rules')).toBeNull();
	});
});

describe('repositories', () => {
	test('parseRepo accepts what the GitHub check route accepts', () => {
		expect(parseRepo('FalkorDB/FalkorDB')).toEqual(['FalkorDB', 'FalkorDB']);
		expect(parseRepo('a-b/c.d_e')).toEqual(['a-b', 'c.d_e']);
		expect(parseRepo('nonsense')).toBeNull();
		expect(parseRepo('a/b/c')).toBeNull();
		expect(parseRepo('a/..')).toBeNull();
		expect(parseRepo('-a/b')).toBeNull();
		expect(parseRepo('')).toBeNull();
	});

	test('normalizeRepo takes a pasted URL down to owner/name', () => {
		expect(normalizeRepo('https://github.com/acme/platform')).toBe('acme/platform');
		expect(normalizeRepo('github.com/acme/platform.git')).toBe('acme/platform');
		expect(normalizeRepo('http://www.github.com/acme/platform/')).toBe('acme/platform');
		expect(normalizeRepo('acme/platform')).toBe('acme/platform');
		expect(normalizeRepo('acme/plat')).toBe('acme/plat');
		expect(normalizeRepo('acme/')).toBe('acme/');
		expect(normalizeRepo('a')).toBe('a');
		expect(normalizeRepo('https://github.com/acme/platform/tree/main/src')).toBe('acme/platform');
		expect(normalizeRepo('https://github.com/acme/platform?tab=readme')).toBe('acme/platform');
		expect(normalizeRepo('https://github.com/acme/platform.git#readme')).toBe('acme/platform');
	});

	test('a private repository is an error unless the data is the company\'s own', () => {
		const sources = [
			{ type: 'github', repo: 'a/open' },
			{ type: 'github', repo: 'a/secret' },
			{ type: 'local_docs', path: 'docs' }
		];
		const fact = (repo: string) => (repo === 'a/secret' ? ('private' as const) : undefined);
		const errors = repoErrors(draft({ sources, data_permission: 'public' }), fact);
		expect(errors).toEqual([{ loc: ['sources', 1, 'repo'], msg: PRIVATE_REPO_MESSAGE }]);
		expect(repoErrors(draft({ sources, data_permission: 'own' }), fact)).toEqual([]);
	});

	test('a repository GitHub cannot find is not an error (the card warns)', () => {
		const sources = [{ type: 'github', repo: 'a/typo' }];
		for (const data_permission of ['public', 'own'] as const) {
			expect(repoErrors(draft({ sources, data_permission }), () => 'missing')).toEqual([]);
		}
		expect(repoErrorFor('missing', 'public')).toBeUndefined();
	});

	test('repoErrorFor: unknown or failed checks never block', () => {
		expect(repoErrorFor(undefined, 'public')).toBeUndefined();
		expect(repoErrorFor('private', 'own')).toBeUndefined();
		expect(repoErrorFor('private', 'synthetic')).toBe(PRIVATE_REPO_MESSAGE);
	});
});

describe('aliases', () => {
	test('rows become a record, skipping rows missing either side', () => {
		const rows = [
			{ name: 'Sam O.', login: 'sokafor' },
			{ name: '', login: 'x' },
			{ name: 'Y', login: '' }
		];
		expect(aliasRowsToRecord(rows)).toEqual({ 'Sam O.': 'sokafor' });
	});

	test('a record becomes rows in key order', () => {
		expect(recordToAliasRows({ a: 'b', c: 'd' })).toEqual([
			{ name: 'a', login: 'b' },
			{ name: 'c', login: 'd' }
		]);
	});
});

describe('splitYamlBlocks', () => {
	const yaml = [
		'slug: acme',
		'name: Acme',
		'window:',
		'  since: 2026-01-01',
		'sources:',
		'  - type: github',
		'    repo: a/b',
		'systems:',
		'  rules: []',
		'  fallback: depth_2',
		''
	].join('\n');

	test('one block per top-level key, with its indented lines', () => {
		const blocks = splitYamlBlocks(yaml);
		expect(blocks.map((b) => b.key)).toEqual(['slug', 'name', 'window', 'sources', 'systems']);
		expect(blocks[3].text).toBe('sources:\n  - type: github\n    repo: a/b');
		expect(blocks[0].text).toBe('slug: acme');
	});

	test('joining the blocks gives the text back', () => {
		expect(splitYamlBlocks(yaml).map((b) => b.text).join('\n') + '\n').toBe(yaml);
	});

	test('empty text has no blocks', () => {
		expect(splitYamlBlocks('')).toEqual([]);
	});
});

describe('defaultDraft', () => {
	test('starts a year back, with the defaults the YAML would have', () => {
		const d = defaultDraft(new Date(2026, 9, 16));
		expect(d.window.since).toBe('2025-10-16');
		expect(d.slug).toBe('');
		expect(d.sources).toEqual([]);
		expect(d.systems).toEqual({ rules: [], fallback: 'depth_2', ignore: [] });
		expect(d.people).toEqual({ bots: [], aliases: {} });
	});
});

describe('debounce', () => {
	beforeEach(() => vi.useFakeTimers());
	afterEach(() => vi.useRealTimers());

	test('runs once, after the quiet period, with the last arguments', () => {
		const fn = vi.fn();
		const run = debounce(fn, 300);
		run(1);
		vi.advanceTimersByTime(200);
		run(2);
		vi.advanceTimersByTime(299);
		expect(fn).not.toHaveBeenCalled();
		vi.advanceTimersByTime(1);
		expect(fn).toHaveBeenCalledTimes(1);
		expect(fn).toHaveBeenCalledWith(2);
	});

	test('cancel drops a pending call', () => {
		const fn = vi.fn();
		const run = debounce(fn, 300);
		run();
		run.cancel();
		vi.advanceTimersByTime(1000);
		expect(fn).not.toHaveBeenCalled();
	});
});

describe('blankSource', () => {
	test('a GitHub source starts with everything on', () => {
		expect(blankSource('github')).toEqual({
			type: 'github',
			repo: '',
			include: ['commits', 'pull_requests', 'issues', 'reviews', 'codeowners', 'repo_docs']
		});
		expect(GITHUB_PARTS).toHaveLength(6);
	});

	test('a folder source starts with an empty path', () => {
		expect(blankSource('local_docs')).toEqual({ type: 'local_docs', path: '' });
		expect(blankSource('canonical_jsonl')).toEqual({ type: 'canonical_jsonl', path: '' });
	});
});

describe('gates', () => {
	const slugPattern = err(['slug'], "String should match pattern '^[a-z0-9][a-z0-9_]*$'");

	function gate(over: Partial<Gate> = {}): Gate {
		return {
			draft: draft(),
			errors: [],
			validating: false,
			answered: true,
			unreachable: false,
			fact: () => undefined,
			repoPending: () => false,
			...over
		};
	}
	const github = (repo: string) => draft({ sources: [{ type: 'github', repo }] });

	test('the first screen asks for the name, not for fields that are not marked', () => {
		const first = gate({ draft: defaultDraft(new Date(2026, 9, 16)), errors: [slugPattern] });
		expect(visibleErrors(first.draft, first.errors)).toEqual([]);
		expect(continueGate(first, 'company')).toEqual({
			blocked: true,
			reason: 'Enter the company name to continue.'
		});
	});

	test('a slug error shows once a name is typed', () => {
		const typed = gate({ draft: draft({ name: 'Acme', slug: '' }), errors: [slugPattern] });
		expect(visibleErrors(typed.draft, typed.errors)).toEqual([slugPattern]);
		expect(continueGate(typed, 'company').reason).toBe('Fix the fields marked above to continue.');
	});

	test('Continue is open when the step is complete and validated', () => {
		expect(continueGate(gate(), 'company')).toEqual({ blocked: false, reason: null });
		expect(continueGate(gate(), 'sources')).toEqual({ blocked: false, reason: null });
	});

	test('Continue waits for a validation in flight, and for the first answer', () => {
		expect(continueGate(gate({ validating: true }), 'company')).toEqual({
			blocked: true,
			reason: 'Checking'
		});
		expect(continueGate(gate({ answered: false }), 'company').blocked).toBe(true);
	});

	test('an unreachable API blocks without a reason (the banner says it)', () => {
		expect(continueGate(gate({ unreachable: true }), 'company')).toEqual({
			blocked: true,
			reason: null
		});
	});

	test('a GitHub check not answered yet keeps Continue shut on Sources', () => {
		const typing = gate({ draft: github('acme/platform'), repoPending: () => true });
		expect(continueGate(typing, 'sources')).toEqual({ blocked: true, reason: 'Checking GitHub' });
		const answered = gate({ draft: github('acme/platform') });
		expect(continueGate(answered, 'sources').blocked).toBe(false);
	});

	test('a repository that is not ready to be checked is not pending', () => {
		const asked: string[] = [];
		const g = gate({
			draft: github(' acme/platform '),
			repoPending: (repo) => (asked.push(repo), false)
		});
		continueGate(g, 'sources');
		expect(asked).toEqual(['acme/platform']);
	});

	test('a private repository under public data keeps Continue shut', () => {
		const g = gate({ draft: github('a/secret'), fact: () => 'private' });
		expect(continueGate(g, 'sources').reason).toBe('Fix the fields marked above to continue.');
		const own = gate({ draft: { ...github('a/secret'), data_permission: 'own' }, fact: () => 'private' });
		expect(continueGate(own, 'sources').blocked).toBe(false);
	});

	test('a repository GitHub cannot find does not shut anything', () => {
		const g = gate({ draft: github('a/typo'), fact: () => 'missing' });
		expect(continueGate(g, 'sources').blocked).toBe(false);
		expect(saveGate(g).blocked).toBe(false);
	});

	test('on the last step, Save says which earlier step to fix', () => {
		const secret = gate({ draft: github('a/secret'), fact: () => 'private' });
		expect(saveGate(secret)).toEqual({
			blocked: true,
			reason: 'Fix the errors in Sources (step 2) first.'
		});
		const noSources = gate({ draft: draft({ sources: [] }) });
		expect(saveGate(noSources).reason).toBe('Sources (step 2): Add at least one source to continue.');
		const noName = gate({ draft: draft({ name: '' }) });
		expect(saveGate(noName).reason).toBe('Company (step 1): Enter the company name to continue.');
	});

	test('a check that lands while on the last step is not silent', () => {
		const pending = gate({ draft: github('a/new'), repoPending: () => true });
		expect(saveGate(pending)).toEqual({ blocked: true, reason: 'Checking GitHub' });
	});

	test('Save also reads errors on its own step', () => {
		const g = gate({ errors: [err(['systems', 'fallback'])] });
		expect(saveGate(g)).toEqual({ blocked: true, reason: 'Fix the fields marked above.' });
	});

	test('Skip ignores rule errors but not the steps before it', () => {
		const rules = gate({
			errors: [err(['systems', 'fallback'])],
			draft: draft({
				systems: { rules: [{ match: 'a/**', system: '' }], fallback: 'depth_2', ignore: [] }
			})
		});
		expect(saveGate(rules).blocked).toBe(true);
		expect(saveGate(rules, true)).toEqual({ blocked: false, reason: null });
		const noName = gate({ draft: draft({ name: ' ' }) });
		expect(saveGate(noName, true).blocked).toBe(true);
	});

	test('Save waits for validation', () => {
		expect(saveGate(gate({ validating: true }))).toEqual({ blocked: true, reason: 'Checking' });
		expect(saveGate(gate())).toEqual({ blocked: false, reason: null });
	});
});

describe('Linear sources', () => {
	const linear = (over: Record<string, unknown> = {}) => ({
		type: 'linear',
		workspace: 'acme',
		teams: ['ENG'],
		...over
	});
	const workspacePattern = "String should match pattern '^[a-z0-9-]+$'";
	const teamPattern = "String should match pattern '^[A-Z][A-Z0-9]{0,6}$'";

	test('Linear is offered last, and a new one starts with no workspace and every team', () => {
		expect(SOURCE_KINDS.at(-1)).toEqual({ type: 'linear', title: 'Linear workspace' });
		expect(blankSource('linear')).toEqual({ type: 'linear', workspace: '', teams: [] });
	});

	test('a Linear source can be added only for own or synthetic data', () => {
		expect(addSourceBlocked('linear', 'public')).toBe(LINEAR_ADD_REASON);
		expect(addSourceBlocked('linear', 'own')).toBeNull();
		expect(addSourceBlocked('linear', 'synthetic')).toBeNull();
		expect(addSourceBlocked('github', 'public')).toBeNull();
		expect(linearErrorFor('public')).toBe(LINEAR_PERMISSION_MESSAGE);
		expect(linearErrorFor('own')).toBeUndefined();
	});

	test('the workspace is required, the teams are not', () => {
		expect(requiredField('github')).toBe('repo');
		expect(requiredField('linear')).toBe('workspace');
		expect(requiredField('local_docs')).toBe('path');
		const with_ = (source: Record<string, unknown>) =>
			incompleteReason(draft({ data_permission: 'own', sources: [source as never] }), 'sources');
		expect(with_(linear({ teams: [] }))).toBeNull();
		expect(with_(linear({ workspace: ' ' }))).toBe(
			'Fill in every source, or remove the ones you do not need.'
		);
	});

	test('a pasted Linear address becomes the workspace key; typing is left alone', () => {
		expect(normalizeWorkspace('https://linear.app/Acme/team/ENG/active')).toBe('acme');
		expect(normalizeWorkspace('linear.app/synthetic-co')).toBe('synthetic-co');
		expect(normalizeWorkspace('linear.app/acme?x=1')).toBe('acme');
		expect(normalizeWorkspace('Acme')).toBe('Acme');
		expect(normalizeWorkspace('')).toBe('');
	});

	test('team keys are trimmed, put in capitals and kept once', () => {
		expect(normalizeTeams([' eng', 'ENG', 'pay', '', 'Pay '])).toEqual(['ENG', 'PAY']);
	});

	test('cleanDraft trims the workspace and normalises the teams', () => {
		const out = cleanDraft(draft({ sources: [linear({ workspace: ' acme ', teams: ['eng', 'ENG'] })] }));
		expect(out.sources[0]).toEqual({ type: 'linear', workspace: 'acme', teams: ['ENG'] });
	});

	test("the API's workspace error shows as a sentence, and not while the field is empty", () => {
		const errors = [err(['sources', 1, 'workspace'], workspacePattern)];
		expect(workspaceMessage(errors, 1, 'Acme')).toBe(WORKSPACE_MESSAGE);
		expect(workspaceMessage(errors, 1, '')).toBeUndefined();
		expect(workspaceMessage(errors, 0, 'Acme')).toBeUndefined();
		expect(workspaceMessage([err(['sources', 1, 'workspace'], 'Field required')], 1, 'x')).toBe(
			'Field required'
		);
	});

	test("the API's team errors name the bad keys once, plus any other error of the list", () => {
		const teams = ['IDN', 'ENG-1', '1AB'];
		const errors = [
			err(['sources', 0, 'teams', 1], teamPattern),
			err(['sources', 0, 'teams', 2], teamPattern),
			err(['sources', 2, 'teams', 0], teamPattern)
		];
		expect(teamsMessage(errors, 0, teams)).toBe(
			'ENG-1, 1AB: team keys are a capital letter, then up to six capitals or digits, like ENG.'
		);
		expect(teamsMessage([], 0, teams)).toBeUndefined();
		expect(teamsMessage([err(['sources', 0, 'teams'], 'Input should be a valid list')], 0, [])).toBe(
			'Input should be a valid list'
		);
	});

	test('a Linear source under Public data is an error on its type, and shuts the gates', () => {
		const pub = draft({ sources: [{ type: 'canonical_jsonl', path: 'x' }, linear()] });
		expect(sourceErrors(pub, () => undefined)).toEqual([
			{ loc: ['sources', 1, 'type'], msg: LINEAR_PERMISSION_MESSAGE }
		]);
		expect(sourceErrors({ ...pub, data_permission: 'synthetic' }, () => undefined)).toEqual([]);
		const g: Gate = {
			draft: pub,
			errors: [],
			validating: false,
			answered: true,
			unreachable: false,
			fact: () => undefined,
			repoPending: () => false
		};
		expect(continueGate(g, 'sources')).toEqual({
			blocked: true,
			reason: 'Fix the fields marked above to continue.'
		});
		expect(saveGate(g).blocked).toBe(true);
		expect(saveGate({ ...g, draft: { ...pub, data_permission: 'own' } })).toEqual({
			blocked: false,
			reason: null
		});
	});
});
