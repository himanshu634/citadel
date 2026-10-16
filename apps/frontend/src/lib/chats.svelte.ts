/**
 * The Ask page's list of past chats for one company (GET .../threads), newest first.
 *
 * Why: the server keeps every chat (brain/agents/history.py), shared by everyone who opens the
 * company. The list is read a page at a time (`more`), refreshed when a question starts (a new
 * chat appears, answering) and when it ends (its status and time move), and loses a chat the
 * moment it is deleted. A refresh keeps the pages already read.
 */
import { api, describeError } from './api/client';
import type { ThreadSummary } from './types';

export class Chats {
	threads = $state<ThreadSummary[]>([]);
	/** `before` for the next page; null: everything is loaded. */
	next = $state<number | null>(null);
	loading = $state(false);
	error = $state<string | null>(null);
	/** A delete in flight or just failed, by chat id. */
	deleting = $state<string | null>(null);

	#token = 0;

	constructor(readonly slug: string) {}

	/** Read the first page again; chats already shown from later pages stay. */
	async refresh(): Promise<void> {
		const token = ++this.#token;
		this.loading = true;
		try {
			const page = await api.threads(this.slug);
			if (token !== this.#token) return;
			const fresh = new Set(page.threads.map((t) => t.id));
			const older = this.threads.filter((t) => !fresh.has(t.id) && this.#olderThanPage(t, page.threads));
			this.threads = [...page.threads, ...older];
			if (!older.length) this.next = page.next;
			this.error = null;
		} catch (e) {
			if (token === this.#token) this.error = describeError(e);
		} finally {
			if (token === this.#token) this.loading = false;
		}
	}

	/** Read the next page. */
	async more(): Promise<void> {
		if (this.next === null || this.loading) return;
		const token = ++this.#token;
		this.loading = true;
		try {
			const page = await api.threads(this.slug, this.next);
			if (token !== this.#token) return;
			const known = new Set(this.threads.map((t) => t.id));
			this.threads = [...this.threads, ...page.threads.filter((t) => !known.has(t.id))];
			this.next = page.next;
			this.error = null;
		} catch (e) {
			if (token === this.#token) this.error = describeError(e);
		} finally {
			if (token === this.#token) this.loading = false;
		}
	}

	/** Delete a chat. Returns false (and says why in `error`) when the server refused. */
	async remove(id: string): Promise<boolean> {
		this.deleting = id;
		try {
			await api.deleteThread(this.slug, id);
			this.threads = this.threads.filter((t) => t.id !== id);
			this.error = null;
			return true;
		} catch (e) {
			this.error = describeError(e);
			return false;
		} finally {
			this.deleting = null;
		}
	}

	#olderThanPage(t: ThreadSummary, page: ThreadSummary[]): boolean {
		const last = page.at(-1);
		return !!last && t.updated_at < last.updated_at;
	}
}
