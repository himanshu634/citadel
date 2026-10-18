/**
 * How many Keeper claims wait for a lead in the current company: the count on the sidebar's
 * "Review claims" item, and the set of their uids (the Systems page links a logged claim to the
 * review page while it still waits).
 *
 * Why here and not in a page: the sidebar sits in the app frame, outside every company page, and
 * must show the count wherever the user is. The review page and the Systems page call `refresh`
 * after something that may change it (a decision, a Keeper run's step); otherwise it is read
 * every 20 s, every 60 s in a hidden tab. A failed read (the company is building, the API is
 * down) shows no count, never an error: the review page says what is wrong.
 */
import { createContext } from 'svelte';
import { api } from './api/client';
import type { Claim } from './types';

export const PENDING_MS = 20_000;
export const PENDING_HIDDEN_MS = 60_000;

export class PendingClaims {
	/** The company the count is for (the current one, while it can be read). */
	slug = $state<string | null>(null);
	/** The claims waiting, newest first; null until read, or when the read failed. */
	claims = $state.raw<Claim[] | null>(null);

	#reads = 0;

	/** The count for `slug`, or null when it is not known. */
	count(slug: string): number | null {
		return this.slug === slug && this.claims ? this.claims.length : null;
	}

	/** The uids waiting in `slug` (empty when not known). */
	uids(slug: string): Set<string> {
		return new Set(this.slug === slug && this.claims ? this.claims.map((c) => c.uid) : []);
	}

	/** Read the claims of `slug` now. Never throws; an answer for a company left meanwhile is dropped. */
	async refresh(slug: string): Promise<void> {
		const mine = ++this.#reads;
		let claims: Claim[] | null;
		try {
			claims = await api.keeper.claims(slug, 'pending_approval');
		} catch {
			claims = null;
		}
		if (mine !== this.#reads || this.slug !== slug) return;
		this.claims = claims;
	}

	/** Take a list a page has just read itself (the review page), so the count needs no read of its own. */
	put(slug: string, claims: Claim[]): void {
		if (this.slug !== slug) return;
		this.#reads++;
		this.claims = claims;
	}

	/** Follow `slug`: read it now and on a timer. Returns the stopper. */
	follow(slug: string): () => void {
		if (this.slug !== slug) {
			this.slug = slug;
			this.claims = null;
		}
		let live = true;
		let timer: ReturnType<typeof setTimeout> | undefined;
		const tick = async () => {
			await this.refresh(slug);
			if (!live) return;
			const hidden = typeof document !== 'undefined' && document.hidden;
			timer = setTimeout(tick, hidden ? PENDING_HIDDEN_MS : PENDING_MS);
		};
		void tick();
		return () => {
			live = false;
			clearTimeout(timer);
		};
	}

	/** Stop showing a count (no company, or one whose graph can't be read). */
	clear(): void {
		this.#reads++;
		this.slug = null;
		this.claims = null;
	}
}

export const [getPendingClaims, setPendingClaims] = createContext<PendingClaims>();
