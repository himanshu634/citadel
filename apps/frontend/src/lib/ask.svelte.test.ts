import { afterEach, describe, expect, test, vi } from 'vitest';
import { AskThread, NOT_RUN, turnFromChat } from './ask.svelte';
import type { ChatTurn, Thread } from './types';

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

	test('a picked model goes with that question only, and the turn keeps it', async () => {
		const fetchMock = serve(run(), run());
		const t = new AskThread('acme');
		await t.ask('First?', 'claude-opus-5-5');
		await t.ask('And then?');
		const bodies = fetchMock.mock.calls.map((c) => JSON.parse((c as unknown as [string, RequestInit])[1].body as string));
		expect(bodies[0]).toEqual({ question: 'First?', model: 'claude-opus-5-5' });
		expect(bodies[1]).toEqual({ question: 'And then?', thread_id: 't1' });
		expect(t.turns.map((x) => x.model)).toEqual(['claude-opus-5-5', null]);
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
		t.replay();
		expect(t.revealed).toBe(0);
		vi.advanceTimersByTime(800);
		expect(t.revealed).toBeNull(); // one graph step: done after the first tick
		t.replay(true);
		expect(t.revealed).toBeNull();
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

	test('each Claude response is kept on its turn with the tools it asked for, and starts and ends are told', async () => {
		const llm = {
			seq: 1,
			text: 'Looking.',
			thinking: null,
			model: 'm',
			stop: 'tool_use',
			ms: 9,
			usage: { input: 1, output: 2, cache_read: 0, cache_write: 0 },
			calls: [{ id: 'a', tool: 'person_profile', kind: 'graph', server: null, input: { login: 'alice' } }]
		};
		const body = run().replace('event: step\n', `event: llm\ndata: ${JSON.stringify(llm)}\n\nevent: step\n`);
		serve(body);
		const started: string[] = [];
		const ended: (string | null)[] = [];
		const t = new AskThread('acme', (id) => started.push(id), (id) => ended.push(id));
		await t.ask('Who is Alice?');
		expect(t.turns[0].calls.map((c) => [c.seq, c.text, c.calls[0].id])).toEqual([[1, 'Looking.', 'a']]);
		expect(started).toEqual(['t1']);
		expect(ended).toEqual(['t1']);
	});

	test('load reopens a saved chat; the next question follows it up', async () => {
		const saved: Thread = {
			id: 't9',
			title: 'Who is Alice?',
			created_at: '2026-10-16T10:00:00Z',
			updated_at: '2026-10-16T10:01:00Z',
			last_status: 'done',
			turns: [chatTurn()]
		};
		const fetchMock = vi.fn(async () => new Response(JSON.stringify(saved), { status: 200 }));
		vi.stubGlobal('fetch', fetchMock);
		const t = new AskThread('acme');
		await t.load('t9');
		expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toBe('/api/companies/acme/threads/t9');
		expect(t.threadId).toBe('t9');
		expect(t.turns).toHaveLength(1);
		expect(t.turns[0].answer?.text).toBe('Alice [1].');

		const asked = serve(run('t9'));
		await t.ask('And Bob?');
		const req = JSON.parse((asked.mock.calls[0] as unknown as [string, RequestInit])[1].body as string);
		expect(req).toEqual({ question: 'And Bob?', thread_id: 't9' });
		expect(t.turns).toHaveLength(2);
	});

	test('a chat that cannot be opened says why and leaves a new chat', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'No chat nope for acme' }), { status: 404 })));
		const t = new AskThread('acme');
		await t.load('nope');
		expect(t.loadError).toBe('No chat nope for acme');
		expect(t.threadId).toBeNull();
		expect(t.loading).toBe(false);
	});
});

function chatTurn(over: Partial<ChatTurn> = {}): ChatTurn {
	const step = { ms: 5, count: 1, error: null, rows: [], nodes: [node], rels: [], status: 'done', result: null, server: null };
	return {
		n: 1,
		question: 'Who is Alice?',
		status: 'done',
		started_at: '2026-10-16T10:00:00Z',
		ended_at: '2026-10-16T10:01:00Z',
		ms: 60000,
		error: null,
		answer: { thread_id: 't9', text: 'Alice [1].', sources: [], path: [], stop: 'tool_use', model: 'm', trace_id: 'tr' },
		calls: [
			{ seq: 1, at: null, model: 'm', stop: 'tool_use', text: 'Looking.', thinking: 'Profile first.', ms: 9, usage: { input: 1, output: 2, cache_read: 0, cache_write: 0 } },
			{ seq: 2, at: null, model: 'm', stop: 'tool_use', text: null, thinking: null, ms: 4, usage: { input: 1, output: 2, cache_read: 0, cache_write: 0 } }
		],
		steps: [
			{ ...step, id: 'a', call: 1, n: 1, tool: 'person_profile', kind: 'graph', input: { login: 'alice' } },
			{ ...step, id: 'm', call: 1, n: null, tool: 'search', kind: 'mcp', server: 'docs', input: { q: 'x' }, result: 'hit' },
			{ ...step, id: 'z', call: 2, n: null, tool: 'submit_answer', kind: 'submit', input: {}, count: null }
		],
		rating: 'up',
		note: null,
		...over
	};
}

describe('turnFromChat', () => {
	test('graph steps and checks make the walk; every call hangs off the response that asked', () => {
		const turn = turnFromChat(chatTurn());
		expect(turn.steps.map((s) => s.id)).toEqual(['a', 'z']);
		expect(turn.calls.map((c) => c.calls.map((x) => [x.id, x.kind]))).toEqual([
			[
				['a', 'graph'],
				['m', 'mcp']
			],
			[['z', 'submit']]
		]);
		expect(turn.calls[0].calls[1]).toMatchObject({ server: 'docs', result: 'hit' });
		expect(turn.calls[0].thinking).toBe('Profile first.');
		expect(turn).toMatchObject({ status: 'done', rating: 'up', rated: 'idle' });
	});

	test('a step a stopped turn never finished is shown as not run', () => {
		const t = chatTurn({ status: 'stopped' });
		t.steps[0] = { ...t.steps[0], status: 'running' };
		expect(turnFromChat(t).steps[0]).toMatchObject({ status: 'done', error: NOT_RUN });
	});
});
