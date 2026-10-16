import { afterEach, describe, expect, test, vi } from 'vitest';
import { AskThread, NOT_RUN } from './ask.svelte';

afterEach(() => {
	vi.unstubAllGlobals();
	vi.useRealTimers();
});

function sse(frames: [string, unknown][]): string {
	return frames.map(([e, d]) => `event: ${e}\ndata: ${JSON.stringify(d)}\n\n`).join('');
}

function serve(...bodies: string[]) {
	const fetchMock = vi.fn(async () => new Response(bodies.shift() ?? '', { status: 200 }));
	vi.stubGlobal('fetch', fetchMock);
	return fetchMock;
}

const node = { uid: 'person:alice', label: 'Person', title: 'alice', url: null };
const run = (thread = 't1') =>
	sse([
		['start', { thread_id: thread }],
		['step', { id: 'a', n: 1, tool: 'person_profile', input: { login: 'alice' } }],
		['step_done', { id: 'a', n: 1, tool: 'person_profile', input: { login: 'alice' }, ms: 5, count: 1, error: null, rows: [], nodes: [node], rels: [] }],
		['step', { id: 'z', n: null, tool: 'submit_answer', input: {} }],
		['step_done', { id: 'z', n: null, tool: 'submit_answer', input: {}, ms: null, count: null, error: null, rows: [], nodes: [], rels: [] }],
		['answer', { thread_id: thread, text: 'Alice [1].', sources: [{ uid: 'person:alice', title: 'alice', url: null, label: 'Person', step: 1 }], path: [], stop: 'tool_use', model: 'm' }]
	]);

describe('AskThread', () => {
	test('a run becomes one turn: steps replaced in place when done, then the answer', async () => {
		serve(run());
		const t = new AskThread('acme');
		await t.ask('Who is Alice?');
		expect(t.turns).toHaveLength(1);
		const [turn] = t.turns;
		expect(turn.status).toBe('done');
		expect(turn.steps.map((s) => [s.id, s.status])).toEqual([
			['a', 'done'],
			['z', 'done']
		]);
		expect(turn.steps[0].nodes).toEqual([node]);
		expect(turn.answer?.text).toBe('Alice [1].');
		expect(t.threadId).toBe('t1');
		expect(t.running).toBe(false);
	});

	test('a follow-up sends the thread id', async () => {
		const fetchMock = serve(run(), run());
		const t = new AskThread('acme');
		await t.ask('First?');
		await t.ask('And then?');
		const body = JSON.parse((fetchMock.mock.calls[1] as unknown as [string, RequestInit])[1].body as string);
		expect(body).toEqual({ question: 'And then?', thread_id: 't1' });
		expect(t.selected).toBe(1);
	});

	test('an error event and a cut stream both end the turn as failed, with a sentence', async () => {
		serve(sse([['start', { thread_id: 'x' }], ['error', { detail: 'No Anthropic credentials.' }]]), sse([['start', { thread_id: 'x' }]]));
		const t = new AskThread('acme');
		await t.ask('One');
		expect(t.turns[0]).toMatchObject({ status: 'failed', error: 'No Anthropic credentials.' });
		await t.ask('Two');
		expect(t.turns[1].status).toBe('failed');
		expect(t.turns[1].error).toMatch(/stopped before it finished/);
	});

	test('a refused request (409) fails the turn with the API sentence', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'This chat is still answering.' }), { status: 409 })));
		const t = new AskThread('acme');
		await t.ask('Hm');
		expect(t.turns[0]).toMatchObject({ status: 'failed', error: 'This chat is still answering.' });
	});

	test('stop aborts the request and marks the turn stopped', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(
				(_: string, init: RequestInit) =>
					new Promise((_, reject) => init.signal!.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError'))))
			)
		);
		const t = new AskThread('acme');
		const asking = t.ask('Slow?');
		expect(t.running).toBe(true);
		t.stop();
		await asking;
		expect(t.turns[0].status).toBe('stopped');
	});

	test('steps still running when the turn ends become "not run", never stuck spinning', async () => {
		serve(
			sse([
				['start', { thread_id: 'x' }],
				['step', { id: 'a', n: 1, tool: 'person_profile', input: {} }],
				['step', { id: 'z', n: null, tool: 'submit_answer', input: {} }]
			])
		);
		const t = new AskThread('acme');
		await t.ask('Q');
		expect(t.turns[0].steps.map((s) => [s.status, s.error])).toEqual([
			['done', NOT_RUN],
			['done', NOT_RUN]
		]);
	});

	test('replay shows the steps one at a time, or all at once under reduced motion', async () => {
		serve(run());
		const t = new AskThread('acme');
		await t.ask('Who is Alice?');
		vi.useFakeTimers();
		t.replay(0);
		expect(t.revealed).toBe(0);
		vi.advanceTimersByTime(800);
		expect(t.revealed).toBeNull(); // one graph step: done after the first tick
		t.replay(0, true);
		expect(t.revealed).toBeNull();
	});

	test('replaying an earlier turn makes it the selected one', async () => {
		serve(run(), run());
		const t = new AskThread('acme');
		await t.ask('First?');
		await t.ask('And then?');
		expect(t.selected).toBe(1);
		vi.useFakeTimers();
		t.replay(0);
		expect([t.selected, t.revealed]).toEqual([0, 0]);
		t.select(1);
		expect([t.selected, t.revealed]).toEqual([1, null]); // selecting another stops the replay
	});

	test('reset starts a new conversation', async () => {
		serve(run());
		const t = new AskThread('acme');
		await t.ask('Q');
		t.reset();
		expect(t.turns).toEqual([]);
		expect(t.threadId).toBeNull();
	});

	test('a thumbs is saved on the answer trace, changed, and put back when the save fails', async () => {
		const traced = run().replace('"thread_id":"t1","text"', '"trace_id":"tr1","thread_id":"t1","text"');
		const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
			if (!init?.body || !String(_url).includes('/feedback')) return new Response(traced, { status: 200 });
			const body = JSON.parse(init.body as string);
			return new Response(JSON.stringify({ trace_id: 'tr1', ...body }), { status: 200 });
		});
		vi.stubGlobal('fetch', fetchMock);
		const t = new AskThread('acme');
		await t.ask('Who is Alice?');
		expect(t.turns[0].answer?.trace_id).toBe('tr1');

		await t.rate(0, 'down', '  wrong person ');
		const [url, init] = fetchMock.mock.calls.at(-1) as unknown as [string, RequestInit];
		expect(url).toBe('/api/companies/acme/traces/tr1/feedback');
		expect(JSON.parse(init.body as string)).toEqual({ rating: 'down', note: 'wrong person' });
		expect([t.turns[0].rating, t.turns[0].note, t.turns[0].rated]).toEqual(['down', 'wrong person', 'saved']);

		await t.rate(0, 'up');
		expect(JSON.parse((fetchMock.mock.calls.at(-1)![1] as RequestInit).body as string)).toEqual({ rating: 'up', note: null });
		expect(t.turns[0].rating).toBe('up');

		fetchMock.mockImplementationOnce(async () => new Response('{"detail":"nope"}', { status: 503 }));
		await t.rate(0, null);
		expect([t.turns[0].rating, t.turns[0].rated]).toEqual(['up', 'failed']);
	});

	test('an answer without a trace cannot be rated', async () => {
		const fetchMock = serve(run());
		const t = new AskThread('acme');
		await t.ask('Q');
		await t.rate(0, 'up');
		expect(fetchMock).toHaveBeenCalledTimes(1);
		expect(t.turns[0].rating).toBeNull();
	});
});
