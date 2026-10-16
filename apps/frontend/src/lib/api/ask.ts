/**
 * Server-sent events over a POST: the Ask route takes a body, which `EventSource` cannot send.
 *
 * Why: `openEvents` (events.ts) wraps EventSource, which only GETs and reconnects for ever. An
 * answer is one request: POST the question, read `text/event-stream` frames from the body until
 * the server ends it, never reconnect (that would ask again). Aborting the signal is Stop: the
 * server sees the stream close and ends the run at its next step.
 */
import { ApiError } from './client';

export interface SseFrame {
	event: string;
	data: string;
}

/**
 * Split a growing buffer into complete frames; returns them and the unfinished rest. Handles
 * `\r\n`, multi-line `data:`, comment lines (`: ping`) and frames split across chunks.
 */
export function parseFrames(buffer: string): { frames: SseFrame[]; rest: string } {
	const blocks = buffer.replace(/\r\n?/g, '\n').split('\n\n');
	const rest = blocks.pop() ?? '';
	const frames: SseFrame[] = [];
	for (const block of blocks) {
		let event = 'message';
		const data: string[] = [];
		for (const line of block.split('\n')) {
			if (line === '' || line.startsWith(':')) continue;
			const colon = line.indexOf(':');
			const field = colon === -1 ? line : line.slice(0, colon);
			let value = colon === -1 ? '' : line.slice(colon + 1);
			if (value.startsWith(' ')) value = value.slice(1);
			if (field === 'event') event = value;
			else if (field === 'data') data.push(value);
		}
		if (data.length) frames.push({ event, data: data.join('\n') });
	}
	return { frames, rest };
}

/**
 * POST `body` as JSON to `/api<path>` and call `onEvent(name, data)` for each frame whose data is
 * JSON, in order. Resolves when the server ends the stream. Throws ApiError for a non-2xx answer
 * (which comes before any event); an abort rejects with the fetch's AbortError.
 */
export async function postEvents(
	path: string,
	body: unknown,
	onEvent: (event: string, data: unknown) => void,
	signal?: AbortSignal
): Promise<void> {
	const response = await fetch(`/api${path}`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
		body: JSON.stringify(body),
		signal
	});
	if (!response.ok) {
		const text = await response.text();
		let detail: unknown = text;
		try {
			const payload = JSON.parse(text);
			detail = payload && typeof payload === 'object' && 'detail' in payload ? payload.detail : payload;
		} catch {
			// Not JSON (a proxy's error page): keep the text.
		}
		throw new ApiError(response.status, detail);
	}
	if (!response.body) return;
	const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
	let buffer = '';
	for (;;) {
		const { value, done } = await reader.read();
		if (done) break;
		const { frames, rest } = parseFrames(buffer + value);
		buffer = rest;
		for (const frame of frames) {
			let data: unknown;
			try {
				data = JSON.parse(frame.data);
			} catch {
				continue;
			}
			onEvent(frame.event, data);
		}
	}
}
