/**
 * The rules of the company form that do not need a browser: which step a validation error
 * belongs to, which messages to show where, what a step still lacks, how a draft is cleaned
 * before it is sent, and how the YAML preview is cut into highlightable blocks.
 *
 * Why: the add-company wizard and Settings share them, and the API checks the shape of a draft but
 * not that a name or a source was given at all. Keeping the rules pure lets vitest cover every
 * branch; the components only draw what these functions return.
 */
import type { CompanyConfig, FieldError, SourceConfig } from './types';

export type Section = 'company' | 'sources' | 'rules';
export const SECTIONS: Section[] = ['company', 'sources', 'rules'];

/** The top-level keys of the company file that each step adds (they get highlighted in the preview). */
export const SECTION_KEYS: Record<Section, string[]> = {
	company: ['slug', 'name', 'data_permission', 'window'],
	sources: ['sources'],
	rules: ['systems', 'people']
};

export type Loc = (string | number)[];

/** The step that shows the field an error's path starts with; null for a path no step owns. */
export function sectionOfLoc(loc: Loc): Section | null {
	const key = String(loc[0] ?? '');
	return SECTIONS.find((s) => SECTION_KEYS[s].includes(key)) ?? null;
}

/** Errors of one step. Errors no step owns go to the first one, so they are never hidden. */
export function errorsIn(errors: FieldError[], section: Section): FieldError[] {
	return errors.filter((e) => (sectionOfLoc(e.loc) ?? 'company') === section);
}

/** Index in `SECTIONS` of the first step with an error, or -1. */
export function firstSectionWithErrors(errors: FieldError[]): number {
	return SECTIONS.findIndex((s) => errorsIn(errors, s).length > 0);
}

/**
 * The four steps of adding a company, as the Stepper shows them on `/new` and on the build page it
 * ends at. One list, so the two pages cannot disagree about what is optional.
 */
export const WIZARD_STEPS: { label: string; hint?: string }[] = [
	{ label: 'Company' },
	{ label: 'Sources' },
	{ label: 'Systems and people', hint: 'Optional' },
	{ label: 'Build' }
];

const SLUG_PATTERN = 'Use lowercase letters, digits and underscores only, like acme_labs';

/**
 * The sentence for an error. A bad slug gets the spec's wording. The slug-taken sentence from the
 * API stays as it came. Anything else loses pydantic's "Value error, " prefix and starts with a
 * capital.
 */
export function friendly(error: FieldError): string {
	const msg = error.msg.replace(/^(Value error|Assertion failed), /, '');
	if (error.loc[0] === 'slug') return /pattern/i.test(msg) ? SLUG_PATTERN : msg;
	return msg.charAt(0).toUpperCase() + msg.slice(1);
}

const startsWith = (loc: Loc, prefix: Loc) =>
	loc.length >= prefix.length && prefix.every((part, i) => loc[i] === part);

/** The message(s) for the field at `prefix`: every error whose path starts with it. */
export function messageAt(errors: FieldError[], prefix: Loc): string | undefined {
	const found = errors.filter((e) => startsWith(e.loc, prefix)).map(friendly);
	if (found.length === 0) return undefined;
	// One message is shown as it came (the slug-taken sentence keeps its own ending); several are
	// told as sentences, each but the last closed with a full stop.
	return found.map((m, i) => (i < found.length - 1 ? m.replace(/\.?$/, '.') : m)).join(' ');
}

/** Errors that none of the rendered fields (`prefixes`) shows. */
export function unmatched(errors: FieldError[], prefixes: Loc[]): FieldError[] {
	return errors.filter((e) => !prefixes.some((p) => startsWith(e.loc, p)));
}

/** A copy of the draft as it should be validated and saved: text trimmed, empty rule rows gone. */
export function cleanDraft(draft: CompanyConfig): CompanyConfig {
	const out: CompanyConfig = JSON.parse(JSON.stringify(draft));
	out.name = out.name.trim();
	out.sources = out.sources.map((source) => {
		const next: SourceConfig = { ...source };
		for (const field of ['repo', 'path']) {
			if (typeof next[field] === 'string') next[field] = next[field].trim();
		}
		return next;
	});
	if (out.systems) {
		out.systems.rules = (out.systems.rules ?? [])
			.map((r) => ({ match: r.match.trim(), system: r.system.trim() }))
			.filter((r) => r.match !== '' || r.system !== '');
		out.systems.ignore = (out.systems.ignore ?? []).map((g) => g.trim()).filter(Boolean);
	}
	if (out.people) out.people.bots = (out.people.bots ?? []).map((b) => b.trim()).filter(Boolean);
	return out;
}

/** The source types the form can add, in the order of its "Add a source" buttons. */
export const SOURCE_KINDS = [
	{ type: 'github', title: 'GitHub repository' },
	{ type: 'local_docs', title: 'Documents folder' },
	{ type: 'canonical_jsonl', title: 'JSONL records' }
] as const;

/** What a GitHub source can read, in file order; all are on for a new source. */
export const GITHUB_PARTS = [
	{ part: 'commits', label: 'Commits' },
	{ part: 'pull_requests', label: 'Pull requests' },
	{ part: 'issues', label: 'Issues' },
	{ part: 'reviews', label: 'Reviews' },
	{ part: 'codeowners', label: 'CODEOWNERS' },
	{ part: 'repo_docs', label: 'Docs in the repo' }
] as const;

/** A new, empty source of `type`. */
export function blankSource(type: string): SourceConfig {
	if (type === 'github') return { type, repo: '', include: GITHUB_PARTS.map((p) => p.part) };
	return { type, path: '' };
}

const filled = (value: unknown) => typeof value === 'string' && value.trim() !== '';

/**
 * What a step still lacks, as a sentence for the footer, or null. The API accepts an empty name,
 * no source and an empty folder, so the form asks for them itself.
 */
export function incompleteReason(draft: CompanyConfig, section: Section): string | null {
	if (section === 'company') {
		return draft.name.trim() === '' ? 'Enter the company name to continue.' : null;
	}
	if (section === 'sources') {
		if (draft.sources.length === 0) return 'Add at least one source to continue.';
		const empty = draft.sources.some((s) => !filled(s.type === 'github' ? s.repo : s.path));
		return empty ? 'Fill in every source, or remove the ones you do not need.' : null;
	}
	const half = (draft.systems?.rules ?? []).some(
		(r) => (r.match.trim() === '') !== (r.system.trim() === '')
	);
	return half ? 'Give each path rule a pattern and a system, or remove the row.' : null;
}

// What GET /api/checks/github/{owner}/{name} accepts (apps/backend/backend/api/checks.py).
const OWNER = /^[A-Za-z0-9][A-Za-z0-9-]*$/;
const NAME = /^[A-Za-z0-9._-]+$/;

/** [owner, name] when `repo` is something the repository check can ask about, else null. */
export function parseRepo(repo: string): [string, string] | null {
	const parts = repo.split('/');
	if (parts.length !== 2) return null;
	const [owner, name] = parts;
	if (!OWNER.test(owner) || !NAME.test(name) || /^\.+$/.test(name)) return null;
	return [owner, name];
}

/**
 * What was typed or pasted into the repository field. A pasted GitHub address is cut down to
 * `owner/name`; anything else is left alone, so "acme/" can still be typed on to "acme/platform".
 */
export function normalizeRepo(text: string): string {
	const url = /^\s*(https?:\/\/)?(www\.)?github\.com\//i;
	if (!url.test(text)) return text;
	const path = text.replace(url, '').trim().replace(/[?#].*$/, '').replace(/\/+$/, '');
	// A link to a page inside the repository (/tree/main, /pulls) still names the repository.
	const [owner, name, ...rest] = path.split('/');
	const repo = rest.length > 0 && name ? `${owner}/${name}` : path;
	return repo.replace(/\.git$/, '');
}

export const PRIVATE_REPO_MESSAGE =
	'This repository is private. Set the data permission to Own, or the build will refuse to read it.';
/** A warning, never an error: the check lets the form warn early, the build is what decides. */
export const MISSING_REPO_MESSAGE =
	'GitHub cannot find this repository. Check the spelling; a private one needs a token that can read it.';

/** What GitHub definitely said about a repository; undefined while unknown or when the check failed. */
export type RepoFact = 'private' | 'missing' | undefined;

/**
 * The error for a repository, or undefined. Only a private repository while the data is not the
 * company's own is an error (the build refuses it); "not found" is a warning the card shows.
 */
export function repoErrorFor(fact: RepoFact, dataPermission: string): string | undefined {
	if (fact === 'private' && dataPermission !== 'own') return PRIVATE_REPO_MESSAGE;
	return undefined;
}

/** One error per GitHub source that the build would refuse: private while the data is not `own`. */
export function repoErrors(draft: CompanyConfig, fact: (repo: string) => RepoFact): FieldError[] {
	const out: FieldError[] = [];
	draft.sources.forEach((s, i) => {
		if (s.type !== 'github' || typeof s.repo !== 'string') return;
		const msg = repoErrorFor(fact(s.repo.trim()), draft.data_permission);
		if (msg) out.push({ loc: ['sources', i, 'repo'], msg });
	});
	return out;
}

/** What a repository's check is in the middle of: nothing answered yet, or a check in flight. */
type RepoPending = (repo: string) => boolean;

/** Everything the Continue, Save and Skip buttons depend on, so one pure function decides them. */
export interface Gate {
	draft: CompanyConfig;
	/** API errors, slug-taken and rejected-create errors together. */
	errors: FieldError[];
	/** A validation of the latest edit is still on its way. */
	validating: boolean;
	/** At least one validation answer has arrived. */
	answered: boolean;
	/** The API cannot be reached (the page says so in a banner). */
	unreachable: boolean;
	fact: (repo: string) => RepoFact;
	repoPending: RepoPending;
}

export interface GateResult {
	blocked: boolean;
	/** Why, as a sentence for the footer; null when open, or when a banner already says it. */
	reason: string | null;
}

/** Errors that a field shows: a graph name nobody has typed yet is not an error to show. */
export function visibleErrors(draft: CompanyConfig, errors: FieldError[]): FieldError[] {
	if (draft.slug === '' && draft.name.trim() === '') return errors.filter((e) => e.loc[0] !== 'slug');
	return errors;
}

type Why = { kind: 'incomplete'; text: string } | { kind: 'errors' } | { kind: 'checking' };

/** Each section's name, as the wizard's steps and the Settings tabs show it. */
export const STEP_NAMES: Record<Section, string> = {
	company: 'Company',
	sources: 'Sources',
	rules: 'Systems and people'
};

/** What stops a step: something missing, errors on screen, or a GitHub check not answered yet. */
function why(g: Gate, section: Section): Why | null {
	const text = incompleteReason(g.draft, section);
	if (text) return { kind: 'incomplete', text };
	if (errorsIn(visibleErrors(g.draft, g.errors), section).length > 0) return { kind: 'errors' };
	if (section === 'sources') {
		if (repoErrors(g.draft, g.fact).length > 0) return { kind: 'errors' };
		const asking = g.draft.sources.some(
			(s) => s.type === 'github' && typeof s.repo === 'string' && g.repoPending(s.repo.trim())
		);
		if (asking) return { kind: 'checking' };
	}
	return null;
}

function result(g: Gate, reason: string | null): GateResult {
	if (g.unreachable) return { blocked: true, reason: null };
	const pending = reason ?? (g.validating || !g.answered ? 'Checking' : null);
	return { blocked: pending !== null, reason: pending };
}

/** Whether Continue is open on `section`, and if not, why. */
export function continueGate(g: Gate, section: Section): GateResult {
	const w = why(g, section);
	if (!w) return result(g, null);
	if (w.kind === 'incomplete') return result(g, w.text);
	return result(g, w.kind === 'errors' ? 'Fix the fields marked above to continue.' : 'Checking GitHub');
}

/**
 * Whether Save and build (or, with `skipRules`, Skip, use defaults) is open on the last step. It
 * looks at every step the button saves, and says which one to go back to.
 */
export function saveGate(g: Gate, skipRules = false): GateResult {
	const sections = skipRules ? SECTIONS.filter((s) => s !== 'rules') : SECTIONS;
	for (const section of sections) {
		const w = why(g, section);
		if (!w) continue;
		const here = section === SECTIONS[SECTIONS.length - 1];
		const where = `${STEP_NAMES[section]} (step ${SECTIONS.indexOf(section) + 1})`;
		if (w.kind === 'checking') return result(g, 'Checking GitHub');
		if (w.kind === 'incomplete') return result(g, here ? w.text : `${where}: ${w.text}`);
		return result(g, here ? 'Fix the fields marked above.' : `Fix the errors in ${where} first.`);
	}
	return result(g, null);
}

export interface AliasRow {
	name: string;
	login: string;
}

/** The "Name to login" table as the `aliases` map; rows missing either side are left out. */
export function aliasRowsToRecord(rows: AliasRow[]): Record<string, string> {
	const out: Record<string, string> = {};
	for (const { name, login } of rows) {
		if (name.trim() && login.trim()) out[name.trim()] = login.trim();
	}
	return out;
}

export function recordToAliasRows(aliases: Record<string, string>): AliasRow[] {
	return Object.entries(aliases).map(([name, login]) => ({ name, login }));
}

export interface YamlBlock {
	/** The top-level key. */
	key: string;
	text: string;
}

/** The YAML cut at its top-level keys: a block is the `key:` line and the lines indented under it. */
export function splitYamlBlocks(yaml: string): YamlBlock[] {
	const blocks: YamlBlock[] = [];
	for (const line of yaml.split('\n')) {
		const top = /^([A-Za-z_][\w-]*):/.exec(line);
		if (top) blocks.push({ key: top[1], text: line });
		else if (line.trim() !== '' && blocks.length > 0) blocks[blocks.length - 1].text += `\n${line}`;
	}
	return blocks;
}

const two = (n: number) => String(n).padStart(2, '0');

/** An empty draft: reads the last year, the defaults the saved file would have. */
export function defaultDraft(today: Date): CompanyConfig {
	const since = new Date(today.getFullYear() - 1, today.getMonth(), today.getDate());
	return {
		slug: '',
		name: '',
		data_permission: 'public',
		window: { since: `${since.getFullYear()}-${two(since.getMonth() + 1)}-${two(since.getDate())}` },
		sources: [],
		systems: { rules: [], fallback: 'depth_2', ignore: [] },
		people: { bots: [], aliases: {} }
	};
}

export interface Debounced<A extends unknown[]> {
	(...args: A): void;
	cancel(): void;
}

/** `fn`, called once `ms` after the last call, with that call's arguments. */
export function debounce<A extends unknown[]>(fn: (...args: A) => void, ms: number): Debounced<A> {
	let timer: ReturnType<typeof setTimeout> | undefined;
	const run = ((...args: A) => {
		clearTimeout(timer);
		timer = setTimeout(() => fn(...args), ms);
	}) as Debounced<A>;
	run.cancel = () => clearTimeout(timer);
	return run;
}
