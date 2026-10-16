/**
 * The add-a-company dialog's state: one repository field, what GitHub and the API said about it,
 * and the two ways out (a new company, or this repo added to the owner's existing company).
 *
 * Why: the dialog asks for a public GitHub repository and nothing else; the API derives the
 * name, slug and window (`/api/onboard/github`). Lookups run 300 ms after the last keystroke and
 * an answer for older text is dropped. The shell owns one instance (context), so the rail's +
 * and the build page's "Add another" open the same dialog. Navigation is the caller's: `create`
 * and `addTo` return the slug whose build page to show.
 */
import { createContext } from 'svelte';
import { ApiError, api, describeError } from './api/client';
import { GITHUB_PARTS, debounce, normalizeRepo, parseRepo } from './onboarding';
import type { FieldError, RepoLookup } from './types';

export type Lookup =
	| { kind: 'checking' }
	| { kind: 'found'; lookup: RepoLookup }
	| { kind: 'private'; repo: string }
	| { kind: 'missing'; repo: string }
	| { kind: 'no_token' }
	| { kind: 'rate_limited' }
	| { kind: 'unreachable' }
	| { kind: 'failed'; message: string };

/** What the dialog draws. `owner` and `taken` are `found` with a company in the way. */
export type View =
	| 'empty'
	| 'typing'
	| 'checking'
	| 'ready'
	| 'owner'
	| 'taken'
	| 'private'
	| 'missing'
	| 'no_token'
	| 'rate_limited'
	| 'unreachable'
	| 'failed';

export const PRIVATE_MESSAGE = 'Citadel reads public repositories only.';

function failure(error: unknown): Lookup {
	if (error instanceof ApiError && error.status === 424) return { kind: 'no_token' };
	if (error instanceof ApiError && error.status === 429) return { kind: 'rate_limited' };
	if (error instanceof ApiError && error.status === 502) return { kind: 'unreachable' };
	return { kind: 'failed', message: describeError(error) }; // the API itself, not GitHub
}

function code(error: unknown): string | null {
	if (!(error instanceof ApiError)) return null;
	const detail = error.detail;
	return detail !== null && typeof detail === 'object' && 'code' in detail
		? String((detail as { code: unknown }).code)
		: null;
}

export class AddCompany {
	open = $state(false);
	text = $state('');
	/** The answer for `repo` (the parsed text); null before the first lookup of it. */
	result = $state.raw<{ repo: string; lookup: Lookup } | null>(null);
	/** The company name as edited; null keeps the suggestion. */
	name = $state<string | null>(null);
	/** The name's editor is open in place of the name. */
	editingName = $state(false);
	busy = $state(false);
	/** Why the last create or add did not work. */
	error = $state<string | null>(null);

	#version = 0;
	/** Bumped by `reset`: a create or add still running for a closed dialog must not touch it. */
	#session = 0;
	#lookup = debounce((repo: string, mine: number) => void this.#ask(repo, mine), 300);

	/** `owner/name` from the field, or null while it is not one yet. */
	get repo(): string | null {
		const parsed = parseRepo(normalizeRepo(this.text.trim()));
		return parsed ? `${parsed[0]}/${parsed[1]}` : null;
	}

	/** The lookup for the current text; a stale answer (older text) counts as none. */
	get lookup(): Lookup | null {
		return this.result && this.result.repo === this.repo ? this.result.lookup : null;
	}

	get found(): RepoLookup | null {
		const l = this.lookup;
		return l?.kind === 'found' ? l.lookup : null;
	}

	get view(): View {
		if (this.text.trim() === '') return 'empty';
		if (this.repo === null) return 'typing';
		const l = this.lookup;
		if (l === null || l.kind === 'checking') return 'checking';
		if (l.kind !== 'found') return l.kind;
		if (l.lookup.company) return 'taken';
		return l.lookup.owner_company ? 'owner' : 'ready';
	}

	/** The name the company gets: the edit, else the suggestion. */
	get companyName(): string {
		return this.name?.trim() || this.found?.name || '';
	}

	/** True when "Add and build" may be pressed. */
	get canCreate(): boolean {
		return (this.view === 'ready' || this.view === 'owner') && !this.busy && this.companyName !== '';
	}

	show(): void {
		this.reset();
		this.open = true;
	}

	reset(): void {
		this.#session++;
		this.#version++;
		this.#lookup.cancel();
		this.text = '';
		this.result = null;
		this.name = null;
		this.editingName = false;
		this.busy = false;
		this.error = null;
	}

	/** The field changed: look the repository up once typing pauses. */
	input(text: string): void {
		this.text = text;
		this.error = null;
		const repo = this.repo;
		if (repo !== null && this.result?.repo === repo) return; // same repo: its lookup stands
		const mine = ++this.#version;
		this.#lookup.cancel();
		this.name = null; // a name typed for another repo is not this one's
		if (repo === null) {
			this.result = null;
			return;
		}
		this.result = { repo, lookup: { kind: 'checking' } };
		this.#lookup(repo, mine);
	}

	/** Ask again now (after a missing token was fixed, or GitHub failed). */
	retry(): Promise<void> {
		const repo = this.repo;
		if (repo === null) return Promise.resolve();
		this.#lookup.cancel();
		this.result = { repo, lookup: { kind: 'checking' } };
		return this.#ask(repo, ++this.#version);
	}

	async #ask(repo: string, mine: number): Promise<void> {
		const [owner, name] = repo.split('/');
		let lookup: Lookup;
		try {
			const answer = await api.lookupRepo(owner, name);
			if (!answer.exists) lookup = { kind: 'missing', repo };
			else if (answer.private) lookup = { kind: 'private', repo: answer.repo };
			else lookup = { kind: 'found', lookup: answer };
		} catch (e) {
			lookup = failure(e);
		}
		if (mine === this.#version) this.result = { repo, lookup };
	}

	/** Make the company and start its build; the slug to show, or null (then `error` says why). */
	async create(): Promise<string | null> {
		const found = this.found;
		if (!found || !this.canCreate) return null;
		const session = this.#session;
		this.busy = true;
		this.error = null;
		try {
			const edited = this.name?.trim();
			const answer = await api.onboard({
				repo: found.repo,
				slug: found.slug ?? undefined,
				...(edited && edited !== found.name ? { name: edited } : {})
			});
			return session === this.#session ? answer.company.slug : null;
		} catch (e) {
			if (session === this.#session) this.#refused(e, found);
			return null;
		} finally {
			if (session === this.#session) this.busy = false;
		}
	}

	/** Add the repository to `slug` (the owner's company); its build fetches only this repo. */
	async addTo(slug: string): Promise<string | null> {
		const found = this.found;
		if (!found || this.busy) return null;
		const session = this.#session;
		this.busy = true;
		this.error = null;
		try {
			const { config } = await api.company(slug);
			const source = { type: 'github', repo: found.repo, include: GITHUB_PARTS.map((p) => p.part) };
			await api.update(slug, { ...config, sources: [...config.sources, source] });
			return session === this.#session ? slug : null;
		} catch (e) {
			if (session === this.#session) this.error = describeError(e);
			return null;
		} finally {
			if (session === this.#session) this.busy = false;
		}
	}

	#refused(e: unknown, found: RepoLookup): void {
		const repo = this.repo ?? found.repo;
		switch (code(e)) {
			case 'private_repo':
				this.result = { repo, lookup: { kind: 'private', repo: found.repo } };
				return;
			case 'not_found':
				this.result = { repo, lookup: { kind: 'missing', repo: found.repo } };
				return;
			case 'repo_taken': {
				const { slug, name } = (e as ApiError).detail as { slug: string; name: string };
				const lookup = { ...found, company: { slug, name } };
				this.result = { repo, lookup: { kind: 'found', lookup } };
				return;
			}
			case 'slug_taken':
				// Taken since the lookup (another tab, the CLI): look again for a free slug.
				this.error = `brain_${found.slug} was taken a moment ago. Press Add and build again.`;
				void this.retry();
				return;
		}
		if (e instanceof ApiError && e.status === 422 && Array.isArray(e.detail)) {
			this.error = (e.detail as FieldError[]).map((f) => f.msg).join(' ');
			return;
		}
		this.error = describeError(e);
	}
}

export const [getAddCompany, setAddCompany] = createContext<AddCompany>();
