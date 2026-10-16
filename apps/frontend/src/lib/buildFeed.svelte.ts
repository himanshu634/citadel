/**
 * The build the page shows for one company, and the live stream that keeps it current.
 *
 * Why: following a build has more cases than the page should hold. The page opens on a running,
 * finished or never-run build; the API closes the event stream when a build ends (which the
 * auto-reconnecting `openEvents` would answer by reconnecting for ever, so the feed closes it
 * itself); a failure can be announced a moment before the build's state says so; and answers for
 * a company the user has left must not be drawn under the one they are on. Every async step
 * checks that its `open` is still the current one.
 */
import { api, ApiError } from './api/client';
import { openEvents } from './api/events';
import { endsBuild, isActive, withEvent } from './buildProgress';
import type { BuildEvent, BuildSnapshot } from './types';

function describe(e: unknown): string {
	if (e instanceof ApiError && typeof e.detail === 'string') return e.detail;
	// A dev proxy answers 500 with no body when nothing listens behind it.
	return "The Citadel API isn't answering. Start it with make api, then try again.";
}

export class BuildFeed {
	/** The build of the company that was opened; null until it is read, or when it never built. */
	snapshot = $state<BuildSnapshot | null>(null);
	/** The company has never built (404). */
	missing = $state(false);
	/** Why the last read or action failed; null when it worked. */
	error = $state<string | null>(null);
	/** A stop was asked for and the build has not ended yet. */
	stopping = $state(false);

	#run = 0;
	#slug = '';
	#stream: (() => void) | null = null;

	/** Read the company's current build and, if it is active, follow it. Supersedes any earlier open. */
	open(slug: string): void {
		this.close();
		this.#slug = slug;
		if (this.snapshot?.slug !== slug) this.snapshot = null;
		this.missing = false;
		this.error = null;
		this.stopping = false;
		void this.#read(this.#run);
	}

	/** Stop following. Answers still on their way are dropped. */
	close(): void {
		this.#run++;
		this.#unfollow();
	}

	/** Ask the build to stop; it ends at its next safe point and the stream says when. */
	async stop(): Promise<void> {
		const run = this.#run;
		this.stopping = true;
		try {
			const snapshot = await api.stopBuild(this.#slug);
			if (run !== this.#run) return;
			this.#set(snapshot);
		} catch (e) {
			if (run !== this.#run) return;
			this.stopping = false;
			if (e instanceof ApiError && e.status === 404) await this.#read(run); // it ended already
			else this.error = describe(e);
		}
	}

	/** Start a build (a full one by default: it also serves "Retry build" and "Retry rebuild"). */
	async start(full = true): Promise<void> {
		const run = this.#run;
		this.error = null;
		try {
			const snapshot = await api.startBuild(this.#slug, full);
			if (run !== this.#run) return;
			this.missing = false;
			this.stopping = false;
			this.#set(snapshot);
			this.#follow(run);
		} catch (e) {
			if (run !== this.#run) return;
			if (e instanceof ApiError && e.status === 409) await this.#read(run); // one is running
			else this.error = describe(e);
		}
	}

	async #read(run: number): Promise<void> {
		try {
			const snapshot = await api.currentBuild(this.#slug);
			if (run !== this.#run) return;
			this.missing = false;
			this.error = null;
			this.#set(snapshot);
			if (isActive(snapshot.state)) this.#follow(run);
		} catch (e) {
			if (run !== this.#run) return;
			if (e instanceof ApiError && e.status === 404) {
				this.snapshot = null;
				this.missing = true;
			} else {
				this.error = describe(e);
			}
		}
	}

	#set(snapshot: BuildSnapshot): void {
		this.snapshot = snapshot;
		if (!isActive(snapshot.state)) this.stopping = false;
	}

	#follow(run: number): void {
		this.#unfollow();
		const slug = this.#slug;
		this.#stream = openEvents(`/api/companies/${encodeURIComponent(slug)}/builds/current/events`, {
			snapshot: (data) => this.#onSnapshot(run, data as BuildSnapshot),
			build: (data) => this.#onEvent(run, data as BuildEvent)
		});
	}

	#unfollow(): void {
		this.#stream?.();
		this.#stream = null;
	}

	/** The stream's first message, and its first after every reconnect: what is true now. */
	#onSnapshot(run: number, snapshot: BuildSnapshot): void {
		if (run !== this.#run || snapshot.slug !== this.#slug) return;
		this.#set(snapshot);
		// The API ends the stream of a build that is over, and `openEvents` would reconnect to it.
		if (!isActive(snapshot.state)) this.#unfollow();
	}

	#onEvent(run: number, event: BuildEvent): void {
		if (run !== this.#run || event.slug !== this.#slug || this.snapshot === null) return;
		this.#set(withEvent(this.snapshot, event));
		if (endsBuild(event)) void this.#settle(run);
	}

	/**
	 * After the build's last event: read its state. A failure is announced before the state
	 * changes, so a build that still looks active keeps its stream; the reconnect delivers a
	 * snapshot with the final state.
	 */
	async #settle(run: number): Promise<void> {
		try {
			const snapshot = await api.currentBuild(this.#slug);
			if (run !== this.#run) return;
			this.#set(snapshot);
			if (!isActive(snapshot.state)) this.#unfollow();
		} catch {
			// The stream reconnects and sends a snapshot; nothing more to do here.
		}
	}
}
