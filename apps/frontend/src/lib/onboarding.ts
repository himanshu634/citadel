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
	return found.map((m) => m.replace(/\.$/, '')).join('. ');
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

// What GET /api/checks/github/{owner}/{name} accepts (apps/backend/brain/api/checks.py).
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
	return text.replace(url, '').trim().replace(/\/+$/, '').replace(/\.git$/, '');
}

export const PRIVATE_REPO_MESSAGE =
	'This repository is private. Set the data permission to Own, or the build will refuse to read it.';
export const MISSING_REPO_MESSAGE =
	'GitHub cannot find this repository. Check the spelling; a private one needs a token that can read it.';

/** What GitHub definitely said about a repository; undefined while unknown or when the check failed. */
export type RepoFact = 'private' | 'missing' | undefined;

/** The error for a repository, or undefined. Private only counts when the data is not the company's own. */
export function repoErrorFor(fact: RepoFact, dataPermission: string): string | undefined {
	if (fact === 'missing') return MISSING_REPO_MESSAGE;
	if (fact === 'private' && dataPermission !== 'own') return PRIVATE_REPO_MESSAGE;
	return undefined;
}

/** One error per GitHub source that the build could not read: not found, or private without `own`. */
export function repoErrors(draft: CompanyConfig, fact: (repo: string) => RepoFact): FieldError[] {
	const out: FieldError[] = [];
	draft.sources.forEach((s, i) => {
		if (s.type !== 'github' || typeof s.repo !== 'string') return;
		const msg = repoErrorFor(fact(s.repo.trim()), draft.data_permission);
		if (msg) out.push({ loc: ['sources', i, 'repo'], msg });
	});
	return out;
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
