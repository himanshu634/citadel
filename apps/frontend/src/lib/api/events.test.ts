import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { openEvents } from './events';

/** Just enough of EventSource for openEvents: named listeners, open/error, close. */
class FakeEventSource {
	static all: FakeEventSource[] = [];
	closed = false;
	private listeners = new Map<string, ((e: { data?: string }) => void)[]>();

	constructor(readonly url: string) {
		FakeEventSource.all.push(this);
	}
	addEventListener(type: string, fn: (e: { data?: string }) => void) {
		this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
	}
	close() {
		this.closed = true;
	}
	emit(type: string, data?: string) {
		for (const fn of this.listeners.get(type) ?? []) fn({ data });
	}
}

beforeEach(() => {
	FakeEventSource.all = [];
	vi.stubGlobal('EventSource', FakeEventSource);
	vi.useFakeTimers();
});
afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
});

const last = () => FakeEventSource.all[FakeEventSource.all.length - 1];

describe('openEvents', () => {
	test('passes the parsed data of a named event to its handler', () => {
		const status = vi.fn();
		openEvents('/api/events', { status });
		last().emit('status', '{"slug":"a"}');
		expect(status).toHaveBeenCalledWith({ slug: 'a' });
		expect(last().url).toBe('/api/events');
	});

	test('ignores data that is not JSON', () => {
		const status = vi.fn();
		openEvents('/api/events', { status });
		last().emit('status', 'not json');
		expect(status).not.toHaveBeenCalled();
	});

	test('calls onOpen on every open and onReconnect only after the first', () => {
		const onOpen = vi.fn();
		const onReconnect = vi.fn();
		openEvents('/api/events', {}, { onOpen, onReconnect });
		last().emit('open');
		expect(onOpen).toHaveBeenCalledTimes(1);
		expect(onReconnect).not.toHaveBeenCalled();

		last().emit('error');
		vi.advanceTimersByTime(1000);
		last().emit('open');
		expect(onOpen).toHaveBeenCalledTimes(2);
		expect(onReconnect).toHaveBeenCalledTimes(1);
	});

	test('reconnects with a doubling delay capped at 30 s, and an open resets it', () => {
		openEvents('/api/events', {});
		const delays: number[] = [];
		for (let i = 0; i < 7; i++) {
			const before = FakeEventSource.all.length;
			last().emit('error');
			expect(last().closed).toBe(true);
			// find the delay: the new source must not exist one ms early, and must exist at the delay
			const expected = Math.min(1000 * 2 ** i, 30_000);
			vi.advanceTimersByTime(expected - 1);
			expect(FakeEventSource.all.length).toBe(before);
			vi.advanceTimersByTime(1);
			expect(FakeEventSource.all.length).toBe(before + 1);
			delays.push(expected);
		}
		expect(delays).toEqual([1000, 2000, 4000, 8000, 16000, 30000, 30000]);

		last().emit('open');
		last().emit('error');
		const before = FakeEventSource.all.length;
		vi.advanceTimersByTime(1000);
		expect(FakeEventSource.all.length).toBe(before + 1);
	});

	test('the close function closes the source and leaves no reconnect timer', () => {
		const status = vi.fn();
		const close = openEvents('/api/events', { status });
		const source = last();
		source.emit('error'); // schedules a reconnect
		close();
		expect(vi.getTimerCount()).toBe(0);
		vi.advanceTimersByTime(60_000);
		expect(FakeEventSource.all).toHaveLength(1);

		// An event already in flight on the old source is ignored.
		source.emit('status', '{"slug":"a"}');
		expect(status).not.toHaveBeenCalled();
	});

	test('closing while connected closes the source', () => {
		const close = openEvents('/api/events', {});
		close();
		expect(last().closed).toBe(true);
		expect(vi.getTimerCount()).toBe(0);
		close(); // idempotent
	});
});
