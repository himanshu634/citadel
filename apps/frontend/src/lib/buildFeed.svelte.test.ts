import { beforeEach, describe, expect, test, vi } from 'vitest';
import type { BuildEvent, BuildSnapshot, BuildState } from './types';

vi.mock('./api/client', async (importOriginal) => {
	const actual = await importOriginal<typeof import('./api/client')>();
	return {
		...actual,
		api: { currentBuild: vi.fn(), stopBuild: vi.fn(), startBuild: vi.fn() }
	};
});
vi.mock('./api/events', () => ({ openEvents: vi.fn() }));

import { api, ApiError } from './api/client';
import { openEvents } from './api/events';
import { BuildFeed } from './buildFeed.svelte';

const current = vi.mocked(api.currentBuild);
const stopBuild = vi.mocked(api.stopBuild);
const startBuild = vi.mocked(api.startBuild);
const open = vi.mocked(openEvents);

type Handlers = Record<string, (data: unknown) => void>;
let streams: { path: string; handlers: Handlers; close: ReturnType<typeof vi.fn> }[];

function ev(stage: BuildEvent['stage'], status: BuildEvent['status'], slug = 'acme'): BuildEvent {
	return { slug, stage, status, source: null, count: null, message: null, at: `t-${stage}-${status}`, totals: null };
}

function snap(state: BuildState, events: BuildEvent[] = [], slug = 'acme'): BuildSnapshot {
	return {
		slug,
		kind: 'build',
		state,
		started_at: 's',
		stages: ['prepare', 'fetch', 'records', 'normalize', 'load'],
		ended_at: null,
		events,
		error: null
	};
}

/** Let pending promises settle. */
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

beforeEach(() => {
	current.mockReset();
	stopBuild.mockReset();
	startBuild.mockReset();
	open.mockReset();
	streams = [];
	open.mockImplementation((path, handlers) => {
		const close = vi.fn();
		streams.push({ path, handlers: handlers as Handlers, close });
		return close;
	});
});

describe('open', () => {
	test('a running build is read, then followed over the company\'s event stream', async () => {
		current.mockResolvedValue(snap('running', [ev('prepare', 'running')]));
		const feed = new BuildFeed();
		feed.open('acme');
		await flush();
		expect(feed.snapshot?.state).toBe('running');
		expect(streams.map((s) => s.path)).toEqual(['/api/companies/acme/builds/current/events']);
	});

	test('a finished build is shown without a stream', async () => {
		for (const state of ['done', 'failed', 'stopped'] as const) {
			current.mockResolvedValue(snap(state));
			const feed = new BuildFeed();
			feed.open('acme');
			await flush();
			expect(feed.snapshot?.state).toBe(state);
		}
		expect(open).not.toHaveBeenCalled();
	});

	test('a company that never built is "missing", not an error, and has no stream', async () => {
		current.mockRejectedValue(new ApiError(404, 'No build for acme yet'));
		const feed = new BuildFeed();
		feed.open('acme');
		await flush();
		expect(feed.missing).toBe(true);
		expect(feed.snapshot).toBeNull();
		expect(feed.error).toBeNull();
		expect(open).not.toHaveBeenCalled();
	});

	test('other failures say so and keep the page usable', async () => {
		current.mockRejectedValue(new ApiError(500, undefined));
		const feed = new BuildFeed();
		feed.open('acme');
		await flush();
		expect(feed.error).toMatch(/isn't answering/);
		expect(feed.missing).toBe(false);
	});

	test('an answer for the company the user left is dropped', async () => {
		let answerOld: (s: BuildSnapshot) => void = () => {};
		current.mockImplementationOnce(() => new Promise((resolve) => (answerOld = resolve)));
		current.mockResolvedValueOnce(snap('done', [], 'other'));
		const feed = new BuildFeed();
		feed.open('acme');
		feed.open('other');
		await flush();
		answerOld(snap('running', [], 'acme'));
		await flush();
		expect(feed.snapshot?.slug).toBe('other');
		expect(streams).toHaveLength(0);
	});

	test('opening again closes the earlier stream', async () => {
		current.mockResolvedValue(snap('running'));
		const feed = new BuildFeed();
		feed.open('acme');
		await flush();
		feed.open('acme');
		await flush();
		expect(streams[0].close).toHaveBeenCalled();
		expect(streams).toHaveLength(2);
	});
});

describe('stream', () => {
	async function running() {
		current.mockResolvedValue(snap('running', [ev('prepare', 'running')]));
		const feed = new BuildFeed();
		feed.open('acme');
		await flush();
		return feed;
	}

	test('a snapshot replaces what is shown; build events are appended', async () => {
		const feed = await running();
		const { handlers } = streams[0];
		handlers.snapshot(snap('running', [ev('prepare', 'running'), ev('prepare', 'done')]));
		handlers.build(ev('fetch', 'running'));
		expect(feed.snapshot?.events.map((e) => `${e.stage}:${e.status}`)).toEqual([
			'prepare:running',
			'prepare:done',
			'fetch:running'
		]);
	});

	test('events of another company are ignored', async () => {
		const feed = await running();
		streams[0].handlers.build(ev('fetch', 'running', 'other'));
		streams[0].handlers.snapshot(snap('done', [], 'other'));
		expect(feed.snapshot?.events).toHaveLength(1);
		expect(streams[0].close).not.toHaveBeenCalled();
	});

	test('a snapshot that is final (the API restarted and stopped the build) closes the stream', async () => {
		const feed = await running();
		streams[0].handlers.snapshot(snap('stopped', [ev('records', 'stopped')]));
		expect(feed.snapshot?.state).toBe('stopped');
		expect(streams[0].close).toHaveBeenCalled();
	});

	test('the last event re-reads the build, and a final state closes the stream', async () => {
		const feed = await running();
		current.mockResolvedValue(snap('done', [ev('prepare', 'running'), ev('done', 'done')]));
		streams[0].handlers.build(ev('done', 'done'));
		await flush();
		expect(feed.snapshot?.state).toBe('done');
		expect(streams[0].close).toHaveBeenCalled();
	});

	test('a failure event can come before the state changes: the stream stays to deliver it', async () => {
		const feed = await running();
		current.mockResolvedValue(snap('running', [ev('prepare', 'running'), ev('fetch', 'failed')]));
		streams[0].handlers.build(ev('fetch', 'failed'));
		await flush();
		expect(feed.snapshot?.state).toBe('running');
		expect(streams[0].close).not.toHaveBeenCalled();
		// The reconnected stream sends the snapshot once the job has failed.
		streams[0].handlers.snapshot(snap('failed', [ev('fetch', 'failed')]));
		expect(feed.snapshot?.state).toBe('failed');
		expect(streams[0].close).toHaveBeenCalled();
	});

	test('nothing arrives after close()', async () => {
		const feed = await running();
		feed.close();
		streams[0].handlers.build(ev('fetch', 'running'));
		expect(streams[0].close).toHaveBeenCalled();
		expect(feed.snapshot?.events).toHaveLength(1);
	});
});

describe('stop', () => {
	test('asks the API, and shows "stopping" while the build is still active', async () => {
		current.mockResolvedValue(snap('running'));
		stopBuild.mockResolvedValue(snap('running'));
		const feed = new BuildFeed();
		feed.open('acme');
		await flush();
		await feed.stop();
		expect(stopBuild).toHaveBeenCalledWith('acme');
		expect(feed.stopping).toBe(true);
		streams[0].handlers.snapshot(snap('stopped', [ev('fetch', 'stopped')]));
		expect(feed.stopping).toBe(false);
	});

	test('a 404 means the build already ended: read it again', async () => {
		current.mockResolvedValueOnce(snap('running'));
		current.mockResolvedValueOnce(snap('done', [ev('done', 'done')]));
		stopBuild.mockRejectedValue(new ApiError(404, 'No build of acme is running'));
		const feed = new BuildFeed();
		feed.open('acme');
		await flush();
		await feed.stop();
		expect(feed.snapshot?.state).toBe('done');
		expect(feed.stopping).toBe(false);
		expect(feed.error).toBeNull();
	});
});

describe('start', () => {
	test('starts a full build and follows it', async () => {
		current.mockResolvedValue(snap('failed', [ev('fetch', 'failed')]));
		startBuild.mockResolvedValue(snap('running', [ev('prepare', 'waiting')]));
		const feed = new BuildFeed();
		feed.open('acme');
		await flush();
		await feed.start();
		expect(startBuild).toHaveBeenCalledWith('acme', true);
		expect(feed.snapshot?.state).toBe('running');
		expect(streams).toHaveLength(1);
	});

	test('a 409 (a build is already running) reads that build instead', async () => {
		current.mockResolvedValueOnce(snap('failed'));
		current.mockResolvedValueOnce(snap('running'));
		startBuild.mockRejectedValue(new ApiError(409, 'A build for acme is already running'));
		const feed = new BuildFeed();
		feed.open('acme');
		await flush();
		await feed.start();
		await flush();
		expect(feed.snapshot?.state).toBe('running');
		expect(streams).toHaveLength(1);
	});

	test('any other failure is shown', async () => {
		current.mockResolvedValue(snap('failed'));
		startBuild.mockRejectedValue(new ApiError(404, 'Unknown company'));
		const feed = new BuildFeed();
		feed.open('acme');
		await flush();
		await feed.start();
		expect(feed.error).toBe('Unknown company');
	});
});
