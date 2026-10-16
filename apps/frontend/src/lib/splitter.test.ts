import { describe, expect, test } from 'vitest';
import { WALK_LIMITS, clampSize, dragTo, keyMove, readSplit } from './splitter';

describe('splitter', () => {
	test('a size is kept between the minimum width and the maximum share', () => {
		expect(clampSize(0.38, 1200)).toBe(0.38);
		expect(clampSize(0.1, 1200)).toBeCloseTo(320 / 1200);
		expect(clampSize(0.9, 1200)).toBe(WALK_LIMITS.max);
		// On a narrow window the minimum wins, but never past the maximum share.
		expect(clampSize(0.2, 400)).toBe(WALK_LIMITS.max);
		expect(clampSize(Number.NaN, 1200)).toBe(WALK_LIMITS.reset);
		expect(clampSize(0.5, 0)).toBe(WALK_LIMITS.reset);
	});

	test('dragging well past the minimum folds the pane; short of that it stops at the minimum', () => {
		expect(dragTo(600, 1200)).toEqual({ size: 0.5, folded: false });
		expect(dragTo(260, 1200)).toEqual({ size: 320 / 1200, folded: false });
		expect(dragTo(200, 1200)).toEqual({ size: WALK_LIMITS.reset, folded: true });
		expect(dragTo(1100, 1200)).toEqual({ size: WALK_LIMITS.max, folded: false });
	});

	test('keys move the line, Home and End go to the ends, Enter folds and opens', () => {
		const split = { size: 0.4, folded: false };
		expect(keyMove(split, 'ArrowLeft', false, 1200)?.size).toBeCloseTo(0.42);
		expect(keyMove(split, 'ArrowRight', true, 1200)?.size).toBeCloseTo(0.3);
		expect(keyMove(split, 'Home', false, 1200)?.size).toBeCloseTo(320 / 1200);
		expect(keyMove(split, 'End', false, 1200)?.size).toBe(WALK_LIMITS.max);
		expect(keyMove(split, 'Enter', false, 1200)).toEqual({ size: 0.4, folded: true });
		expect(keyMove({ size: 0.4, folded: true }, 'ArrowLeft', false, 1200)?.folded).toBe(false);
		expect(keyMove(split, 'a', false, 1200)).toBeNull();
	});

	test('a stored split is read back, and anything odd falls back to the default', () => {
		expect(readSplit('{"size":0.5,"folded":true}')).toEqual({ size: 0.5, folded: true });
		expect(readSplit(null)).toEqual({ size: WALK_LIMITS.reset, folded: false });
		expect(readSplit('not json')).toEqual({ size: WALK_LIMITS.reset, folded: false });
		expect(readSplit('{"size":4}')).toEqual({ size: WALK_LIMITS.reset, folded: false });
	});
});
