/**
 * Builds for the /components gallery: running, queued, done, failed, stopped, a rebuild, a
 * build with a skipped source, and the embed stage loading its model, running and skipped. Event times are fixed local times so the log reads the same on
 * every visit.
 */
import type { BuildEvent, BuildSnapshot, BuildStage, BuildState, BuildStatus } from '$lib/types';

const GITHUB = 'github:acme-labs/platform';
const DOCS = 'local_docs:data/inbox/acme_labs/docs';
const BUILD: BuildStage[] = ['prepare', 'fetch', 'records', 'normalize', 'load', 'embed'];
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

const loaded = () => [
	...fetched(),
	ev('records', 'done', GITHUB, 2310),
	ev('normalize', 'done', GITHUB, 2290),
	ev('load', 'done', GITHUB, 6844)
];

export const done = snapshot('done', [
	...loaded(),
	ev('embed', 'running'),
	ev('embed', 'done', null, 1872),
	ev('done', 'done')
]);

const LOADING_MODEL = 'Loading the embedding model (the first run downloads about 0.2 GB)';

/** Every source loaded; the embed stage waits for the model before its first batch. */
export const embedLoading = snapshot('running', [...loaded(), ev('embed', 'running', null, undefined, LOADING_MODEL)]);

/** Every source loaded; the text is being embedded, one batch at a time. */
export const embedding = snapshot('running', [
	...loaded(),
	ev('embed', 'running', null, undefined, LOADING_MODEL),
	ev('embed', 'running', null, 640)
]);

/** Embeddings are off: the build finishes, and the embed cell says why it was skipped. */
export const embedSkipped = snapshot('done', [
	...loaded(),
	ev(
		'embed',
		'skipped',
		null,
		undefined,
		'Embeddings are off (EMBEDDING_PROVIDER=none), so semantic search finds nothing. ' +
			'Set EMBEDDING_PROVIDER=fastembed and run make embed.'
	),
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
