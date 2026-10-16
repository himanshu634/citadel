/**
 * What GitHub says about the repositories typed into source cards, and whether a token exists.
 *
 * Why: a card learns early that a repository is private (the fetch would refuse it unless the
 * data is the company's own) or that no token is configured. The wizard also needs the answers to
 * decide whether Continue is open, so they live here, keyed by `owner/name`, and not in a card.
 * Only a definite answer blocks (private without `own`, not found; see `repoErrors`): a missing
 * token, a rate limit or a GitHub outage must not stop someone from adding a company.
 */
import { SvelteMap, SvelteSet } from 'svelte/reactivity';
import { ApiError, api } from './api/client';
import { parseRepo, type RepoFact } from './onboarding';

export type RepoResult =
	| { kind: 'found'; private: boolean }
	| { kind: 'missing' }
	| { kind: 'no_token' }
	| { kind: 'rate_limited' }
	| { kind: 'unreachable' };

/** Answers worth keeping; the others (no token yet, rate limit, outage) are asked again. */
const settled = (r: RepoResult | undefined) => r?.kind === 'found' || r?.kind === 'missing';

function failure(error: unknown): RepoResult {
	if (error instanceof ApiError && error.status === 424) return { kind: 'no_token' };
	if (error instanceof ApiError && error.status === 429) return { kind: 'rate_limited' };
	return { kind: 'unreachable' };
}

export class RepoChecks {
	/** Where a token comes from; null when there is none; undefined until known (or API down). */
	token = $state<'env' | 'gh' | null | undefined>(undefined);
	results = new SvelteMap<string, RepoResult>();
	checking = new SvelteSet<string>();

	#inFlight = new Map<string, Promise<void>>();

	async checkToken(): Promise<void> {
		try {
			this.token = (await api.githubToken()).token;
		} catch {
			this.token = undefined;
		}
	}

	/** What GitHub definitely said about `repo`; undefined while unknown or when the check failed. */
	fact(repo: string): RepoFact {
		const result = this.results.get(repo);
		if (result?.kind === 'missing') return 'missing';
		return result?.kind === 'found' && result.private ? 'private' : undefined;
	}

	/** Ask about `owner/name` unless it was answered already (`force` asks again). */
	check(repo: string, force = false): Promise<void> {
		const parsed = parseRepo(repo);
		if (!parsed) return Promise.resolve();
		if (!force && settled(this.results.get(repo))) return Promise.resolve();
		const running = this.#inFlight.get(repo);
		if (running) return running;
		this.checking.add(repo);
		const run = (async () => {
			try {
				const answer = await api.githubRepo(parsed[0], parsed[1]);
				this.results.set(
					repo,
					answer.exists ? { kind: 'found', private: answer.private === true } : { kind: 'missing' }
				);
			} catch (error) {
				this.results.set(repo, failure(error));
			} finally {
				this.checking.delete(repo);
				this.#inFlight.delete(repo);
			}
		})();
		this.#inFlight.set(repo, run);
		return run;
	}
}

/** One shared instance: the cards and the wizard read the same answers. */
export const repoChecks = new RepoChecks();
