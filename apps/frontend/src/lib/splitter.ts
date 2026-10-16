/**
 * The rules of a window splitter: how wide the pane it controls may be, when a drag folds it, and
 * what each key does (the WAI-ARIA window splitter pattern).
 *
 * Why: the Ask page's walk column is resized by dragging the line between it and the chat, and
 * the same numbers must hold for a drag, a key press and a width read back from storage. Pure: no
 * Svelte, no DOM. The pane's size is a fraction of its container, so it keeps its share when the
 * window is resized.
 */

export interface SplitLimits {
	/** The narrowest the pane may be, in px. */
	min: number;
	/** The widest, as a fraction of the container. */
	max: number;
	/** Where a double-click (and a first visit) puts it. */
	reset: number;
	/** Dragging this many px narrower than `min` folds the pane. */
	foldSlack: number;
}

export const WALK_LIMITS: SplitLimits = { min: 320, max: 0.65, reset: 0.38, foldSlack: 80 };

export interface Split {
	size: number;
	folded: boolean;
}

/** The fraction closest to `size` that fits `container` px (min wins over max on a narrow window). */
export function clampSize(size: number, container: number, limits: SplitLimits = WALK_LIMITS): number {
	if (!(container > 0)) return limits.reset;
	const lo = Math.min(limits.min / container, limits.max);
	return Math.min(limits.max, Math.max(lo, Number.isFinite(size) ? size : limits.reset));
}

/** The pane is `width` px wide after a drag: folded when dragged well past its minimum. */
export function dragTo(width: number, container: number, limits: SplitLimits = WALK_LIMITS): Split {
	if (width < limits.min - limits.foldSlack) return { size: limits.reset, folded: true };
	return { size: clampSize(width / container, container, limits), folded: false };
}

/** Arrow keys move the line 2% (10% with Shift); the pane is on the far side, so Left widens it. */
export function keyMove(
	split: Split,
	key: string,
	shift: boolean,
	container: number,
	limits: SplitLimits = WALK_LIMITS
): Split | null {
	const step = shift ? 0.1 : 0.02;
	switch (key) {
		case 'ArrowLeft':
			return { size: clampSize(split.size + step, container, limits), folded: false };
		case 'ArrowRight':
			return { size: clampSize(split.size - step, container, limits), folded: false };
		case 'Home':
			return { size: clampSize(0, container, limits), folded: false };
		case 'End':
			return { size: limits.max, folded: false };
		case 'Enter':
			return { size: split.size, folded: !split.folded };
		default:
			return null;
	}
}

/** A stored split, or the default when there is none or it does not parse. */
export function readSplit(raw: string | null, limits: SplitLimits = WALK_LIMITS): Split {
	if (!raw) return { size: limits.reset, folded: false };
	try {
		const v = JSON.parse(raw) as Partial<Split>;
		const size = typeof v.size === 'number' && v.size > 0 && v.size < 1 ? v.size : limits.reset;
		return { size, folded: v.folded === true };
	} catch {
		return { size: limits.reset, folded: false };
	}
}
