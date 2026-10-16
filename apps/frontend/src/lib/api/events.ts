/**
 * A server-sent-events subscription that reconnects on its own.
 *
 * Why: the browser's EventSource retries at a fixed short delay and never gives up, which hammers
 * a stopped API. This one closes the failed source and retries with a doubling delay (1 s up to
 * 30 s). Events can be lost while it is down, so it tells the caller on every open and the caller
 * re-reads what it shows. The closing function stops it for good: no source, no timer left.
 */

const FIRST_DELAY_MS = 1_000;
const MAX_DELAY_MS = 30_000;

export interface EventsOptions {
	/** Every time the stream opens: the first connect and each reconnect. */
	onOpen?: () => void;
	/** Only for a reconnect, after events may have been missed. */
	onReconnect?: () => void;
}

/**
 * Subscribe to `path`. `handlers` maps an SSE event name to a function that gets the event's data
 * parsed as JSON (data that is not JSON is dropped). Returns the function that closes it.
 */
export function openEvents(
	path: string,
	handlers: Record<string, (data: unknown) => void>,
	opts: EventsOptions = {}
): () => void {
	let source: EventSource | null = null;
	let timer: ReturnType<typeof setTimeout> | null = null;
	let delay = FIRST_DELAY_MS;
	let opened = false;
	let closed = false;

	function connect() {
		timer = null;
		const current = new EventSource(path);
		source = current;
		// A source we closed can still deliver what was already queued: only the live one counts.
		const live = () => !closed && source === current;

		current.addEventListener('open', () => {
			if (!live()) return;
			delay = FIRST_DELAY_MS;
			const reconnect = opened;
			opened = true;
			opts.onOpen?.();
			if (reconnect) opts.onReconnect?.();
		});
		current.addEventListener('error', () => {
			if (!live()) return;
			current.close();
			source = null;
			timer = setTimeout(connect, delay);
			delay = Math.min(delay * 2, MAX_DELAY_MS);
		});
		for (const [name, handler] of Object.entries(handlers)) {
			current.addEventListener(name, (event) => {
				if (!live()) return;
				let data: unknown;
				try {
					data = JSON.parse((event as MessageEvent<string>).data);
				} catch {
					return;
				}
				handler(data);
			});
		}
	}

	connect();

	return () => {
		closed = true;
		if (timer !== null) clearTimeout(timer);
		timer = null;
		source?.close();
		source = null;
	};
}
