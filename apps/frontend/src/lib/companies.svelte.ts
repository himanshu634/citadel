/**
 * The companies the UI shows, their live statuses, and which one is current.
 *
 * Why: the rail, the top bar and every page read this one object, so a status change reaches them
 * all at once. `guard` is how a page keeps one company's answer from appearing under another: a
 * response for a company that is no longer current is dropped (spec: never show one company's
 * data under another).
 */
import { createContext } from 'svelte';
import { api, describeError } from './api/client';
import { openEvents } from './api/events';
import type { Company } from './types';

/** The API's order: valid companies by name (case-insensitive, then slug), invalid ones by slug. */
function order(a: Company, b: Company): number {
	const invalid = Number(a.status === 'invalid') - Number(b.status === 'invalid');
	if (invalid !== 0) return invalid;
	if (a.status === 'invalid') return compare(a.slug, b.slug);
	return compare(a.name.toLowerCase(), b.name.toLowerCase()) || compare(a.slug, b.slug);
}

const compare = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

export class Companies {
	list = $state<Company[]>([]);
	/** The slug of the company the route shows; the shell keeps it in step with the URL. */
	current = $state<string | null>(null);
	/** True once a load has succeeded: `list` is then what the API said, not a guess. */
	ready = $state(false);
	/** Why the last load failed (null when it worked), for "Can't reach the Citadel API". */
	error = $state<string | null>(null);

	#loads = 0;
	#inFlight = 0;
	/** Status events that arrived while a load was in flight; the load's answer may predate them. */
	#during: Company[] = [];

	get currentCompany(): Company | undefined {
		return this.current === null ? undefined : this.byslug(this.current);
	}

	byslug(slug: string): Company | undefined {
		return this.list.find((c) => c.slug === slug);
	}

	/** Read the list. Never throws: a failure sets `error` and keeps the list already shown. */
	async load(): Promise<void> {
		const mine = ++this.#loads;
		this.#inFlight++;
		try {
			const list = await api.companies();
			if (mine !== this.#loads) return; // a later load started and decides
			this.list = [...list].sort(order);
			for (const company of this.#during) this.#put(company);
			this.ready = true;
			this.error = null;
		} catch (e) {
			if (mine !== this.#loads) return;
			this.error = describeError(e);
		} finally {
			if (--this.#inFlight === 0) this.#during = [];
		}
	}

	/** Take a company as the API sent it (a `status` event): replace it by slug, or add it. */
	apply(company: Company): void {
		if (this.#inFlight > 0) this.#during.push(company);
		this.#put(company);
	}

	#put(company: Company): void {
		const rest = this.list.filter((c) => c.slug !== company.slug);
		this.list = [...rest, company].sort(order);
	}

	/** `value` if it answers `slug` and `slug` is still the current company, else null. */
	guard<T extends { slug: string }>(slug: string, value: T): T | null {
		return value.slug === slug && slug === this.current ? value : null;
	}

	/** Load, then follow `/api/events`; every (re)connect re-reads the list. Returns the stopper. */
	start(): () => void {
		void this.load();
		return openEvents(
			'/api/events',
			{ status: (data) => this.apply(data as Company) },
			{ onOpen: () => void this.load() }
		);
	}
}

export const [getCompanies, setCompanies] = createContext<Companies>();
