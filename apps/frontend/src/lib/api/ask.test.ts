import { afterEach, describe, expect, test, vi } from 'vitest';
import { parseFrames, postEvents } from './ask';
import { ApiError } from './client';

afterEach(() => vi.unstubAllGlobals());

describe('parseFrames', () => {
	test('reads event and data, keeps an unfinished frame for later', () => {
		const { frames, rest } = parseFrames('event: step\ndata: {"n":1}\n\nevent: answ');
		expect(frames).toEqual([{ event: 'step', data: '{"n":1}' }]);
		expect(rest).toBe('event: answ');
	});

	test('handles CRLF, comments (pings), multi-line data and a frame without event', () => {
		const { frames } = parseFrames(': ping - 2026\r\n\r\nevent: a\r\ndata: {"x":\r\ndata: 1}\r\n\r\ndata: 2\n\n');
		expect(frames).toEqual([
			{ event: 'a', data: '{"x":\n1}' },
			{ event: 'message', data: '2' }
		]);
	});
});

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
	const enc = new TextEncoder();
	return new ReadableStream({
		start(controller) {
			for (const c of chunks) controller.enqueue(enc.encode(c));
			controller.close();
		}
	});
}

describe('postEvents', () => {
	test('POSTs the body and delivers each JSON frame in order, across split chunks', async () => {
		const fetchMock = vi.fn(
			async () =>
				new Response(streamOf(['event: start\ndata: {"thread_id":"a"}\n', '\nevent: step\nda', 'ta: {"n":1}\n\n']), {
					status: 200,
					headers: { 'Content-Type': 'text/event-stream' }
				})
		);
		vi.stubGlobal('fetch', fetchMock);
		const seen: [string, unknown][] = [];
		await postEvents('/companies/acme/ask', { question: 'q' }, (e, d) => seen.push([e, d]));
		expect(seen).toEqual([
			['start', { thread_id: 'a' }],
			['step', { n: 1 }]
		]);
		expect(fetchMock).toHaveBeenCalledWith(
			'/api/companies/acme/ask',
			expect.objectContaining({ method: 'POST', body: JSON.stringify({ question: 'q' }) })
		);
	});

	test('a refusal before the stream throws ApiError with the detail', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'busy' }), { status: 409 })));
		const err = await postEvents('/x', {}, () => {}).catch((e) => e);
		expect(err).toBeInstanceOf(ApiError);
		expect(err.status).toBe(409);
		expect(err.detail).toBe('busy');
	});
});
