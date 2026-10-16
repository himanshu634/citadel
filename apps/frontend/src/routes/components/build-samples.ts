/**
 * Builds for the /components gallery: running, queued, done, failed, stopped, a rebuild, and a
 * build with a skipped source. Event times are fixed local times so the log reads the same on
 * every visit.
 */
import type { BuildEvent, BuildSnapshot, BuildStage, BuildState, BuildStatus } from '$lib/types';

const GITHUB = 'github:acme-labs/platform';
const DOCS = 'local_docs:data/inbox/acme_labs/docs';
const BUILD: BuildStage[] = ['prepare', 'fetch', 'records', 'normalize', 'load'];
const REBUILD: BuildStage[] = ['reset', ...BUILD];

let tick = 0;
function ev(
	stage: BuildStage,
	status: BuildStatus,
	source: string | null = null,
	count?: number,
	message?: string
): BuildEvent {
	tick += 3;
	return {
		slug: 'acme_labs',
		stage,
		status,
		source,
		count: count ?? null,
		message: message ?? null,
		at: new Date(2026, 9, 16, 9, 41, tick % 60).toISOString(),
		totals: null
	};
}

function snapshot(
	state: BuildState,
	events: BuildEvent[],
	extra: Partial<BuildSnapshot> = {}
): BuildSnapshot {
	return {
		slug: 'acme_labs',
		kind: 'build',
		state,
		started_at: new Date(2026, 9, 16, 9, 41, 0).toISOString(),
		stages: BUILD,
		ended_at: state === 'queued' || state === 'running' ? null : new Date(2026, 9, 16, 9, 43).toISOString(),
		events,
		error: null,
		...extra
	};
}

const fetched = () => [
	ev('prepare', 'running'),
	ev('prepare', 'done'),
	ev('fetch', 'running', GITHUB),
	ev('fetch', 'done', GITHUB, 2310)
];

/** Fetched, and loading the records: the usual look of a running build. */
export const running = snapshot('running', [
	...fetched(),
	ev('records', 'running', GITHUB),
	ev('records', 'running', GITHUB, 1204)
]);

export const queued = snapshot('queued', [ev('prepare', 'waiting')]);

/** The folder source is skipped: nothing to read, and the rest of the graph builds without it. */
export const skippedSource = snapshot('running', [
	...fetched(),
	ev('fetch', 'running', DOCS),
	ev('fetch', 'done', DOCS),
	ev('records', 'done', GITHUB, 2310),
	ev('normalize', 'done', GITHUB, 2290),
	ev('load', 'running', GITHUB),
	ev('records', 'skipped', DOCS, undefined, 'Folder not found. Put files there and choose Sync now.')
]);

export const done = snapshot('done', [
	...fetched(),
	ev('records', 'done', GITHUB, 2310),
	ev('normalize', 'done', GITHUB, 2290),
	ev('load', 'done', GITHUB, 6844),
	ev('done', 'done')
]);

export const failed = snapshot(
	'failed',
	[
		ev('prepare', 'running'),
		ev('prepare', 'done'),
		ev('fetch', 'running', GITHUB),
		ev('fetch', 'failed', GITHUB, undefined, 'GitHub rate limit reached; resets at 10:12')
	],
	{ error: 'GitHub rate limit reached; resets at 10:12. Set GITHUB_TOKEN for a higher limit.' }
);

/** A stop between two sources: the stage has no source to put it on. */
export const stopped = snapshot('stopped', [
	...fetched(),
	ev('records', 'done', GITHUB, 2310),
	ev('normalize', 'stopped')
]);

export const rebuild = snapshot(
	'running',
	[
		ev('reset', 'running'),
		ev('reset', 'done'),
		ev('prepare', 'running'),
		ev('prepare', 'done'),
		ev('fetch', 'running', GITHUB),
		ev('fetch', 'done', GITHUB, 2310),
		ev('records', 'running', GITHUB, 800)
	],
	{ kind: 'rebuild', stages: REBUILD }
);
