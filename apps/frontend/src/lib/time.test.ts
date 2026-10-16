import { describe, expect, test } from 'vitest';
import { ago } from './time';

const now = Date.parse('2026-10-16T12:00:00Z');

describe('ago', () => {
	test('counts up from just now to days, then shows a date', () => {
		expect(ago('2026-10-16T11:59:30Z', now)).toBe('just now');
		expect(ago('2026-10-16T11:55:00Z', now)).toBe('5 min ago');
		expect(ago('2026-10-16T09:00:00Z', now)).toBe('3 h ago');
		expect(ago('2026-10-14T12:00:00Z', now)).toBe('2 d ago');
		expect(ago('2026-09-01T12:00:00Z', now)).toMatch(/2026/);
	});

	test('a bad time is empty, a future one is just now', () => {
		expect(ago('nope', now)).toBe('');
		expect(ago('2026-10-16T13:00:00Z', now)).toBe('just now');
	});
});
