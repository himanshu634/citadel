/**
 * "Sync now": start an incremental build for one company and say how it went.
 *
 * Why: the overview and Settings both offer Sync now. One function decides what the API's answers
 * mean (a 409 is "a build is already running", which is not a failure), so the two pages cannot
 * drift apart. The pages only draw the outcome.
 */
import { ApiError, api, describeError } from './api/client';

export type SyncOutcome =
	/** The build started (it reads only what is new since the last sync). */
	| { kind: 'started' }
	/** The API refused because a build for this company is already running. */
	| { kind: 'running' }
	| { kind: 'failed'; message: string };

export async function startSync(slug: string): Promise<SyncOutcome> {
	try {
		await api.startBuild(slug);
		return { kind: 'started' };
	} catch (e) {
		if (e instanceof ApiError && e.status === 409) return { kind: 'running' };
		return { kind: 'failed', message: describeError(e) };
	}
}
