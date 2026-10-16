<!--
@component
The line between two side-by-side panes that resizes the one after it (a WAI-ARIA window
splitter). Drag it, or focus it and use the arrow keys (Shift for bigger steps), Home and End;
Enter folds the pane and opens it again; a double-click puts it back to its default width. Dragging
well past the narrowest width folds the pane and keeps the width it had before the drag, so it
opens again at that width. A hairline at rest; on hover, focus or drag it
thickens to accent and shows its grip. The parent places it (absolutely, full height) and keeps
`size` (a fraction of `container`) and `folded`; `onsettle` fires once a drag or key press is done,
for saving. Rules in `src/lib/splitter.ts`.
-->
<script lang="ts">
	import { WALK_LIMITS, clampSize, dragTo, keyMove, type SplitLimits } from '$lib/splitter';

	type Props = {
		/** The controlled pane's share of the container, 0 to 1. */
		size: number;
		folded: boolean;
		/** The container's width in px, which `size` is a share of. */
		container: number;
		/** The container's right edge in viewport px: the pane runs from the line to here. */
		right: number;
		/** What the pane is, for the accessible name ("Resize the walk column"). */
		label: string;
		/** The id of the pane it resizes. */
		controls?: string;
		limits?: SplitLimits;
		onsettle?: () => void;
	};

	let {
		size = $bindable(),
		folded = $bindable(),
		container,
		right,
		label,
		controls,
		limits = WALK_LIMITS,
		onsettle
	}: Props = $props();

	let dragging = $state(false);
	/** The size when the drag began: a fold by drag keeps it. */
	let before = 0;
	const percent = $derived(folded ? 0 : Math.round(size * 100));
	const widest = $derived(Math.round(clampSize(1, container, limits) * 100));

	function down(e: PointerEvent) {
		if (e.button !== 0) return;
		e.preventDefault();
		(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
		before = size;
		dragging = true;
	}
	function move(e: PointerEvent) {
		if (!dragging) return;
		const next = dragTo(right - e.clientX, container, before, limits);
		size = next.size;
		folded = next.folded;
	}
	function up() {
		if (!dragging) return;
		dragging = false;
		onsettle?.();
	}
	function key(e: KeyboardEvent) {
		const next = keyMove({ size, folded }, e.key, e.shiftKey, container, limits);
		if (!next) return;
		e.preventDefault();
		size = next.size;
		folded = next.folded;
		onsettle?.();
	}
	function reset() {
		size = limits.reset;
		folded = false;
		onsettle?.();
	}
</script>

<!-- A focusable separator is an interactive widget in the WAI-ARIA window splitter pattern. -->
<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div
	class={['splitter', { dragging }]}
	role="separator"
	tabindex="0"
	aria-orientation="vertical"
	aria-label={label}
	aria-controls={controls}
	aria-valuenow={percent}
	aria-valuemin={0}
	aria-valuemax={widest}
	aria-valuetext={folded ? 'Folded' : `${percent}% wide`}
	onpointerdown={down}
	onpointermove={move}
	onpointerup={up}
	onpointercancel={up}
	onkeydown={key}
	ondblclick={reset}
>
	<span class="line" aria-hidden="true"></span>
	<span class="grip" aria-hidden="true"></span>
</div>

<style>
	.splitter {
		position: relative;
		display: flex;
		justify-content: center;
		width: var(--splitter-hit);
		height: 100%;
		cursor: col-resize;
		touch-action: none;
		outline: none;
	}
	.line {
		width: var(--border-hair);
		height: 100%;
		background: var(--color-line);
		transition:
			width var(--duration-fast) var(--ease-out),
			background-color var(--duration-fast) var(--ease-out);
	}
	.grip {
		position: absolute;
		top: 50%;
		left: 50%;
		width: var(--splitter-grip-w);
		height: var(--splitter-grip-h);
		border-radius: var(--radius-full);
		background: var(--color-line-strong);
		transform: translate(-50%, -50%);
		opacity: 0;
		transition: opacity var(--duration-fast) var(--ease-out);
	}
	.splitter:hover .grip,
	.splitter:focus-visible .grip,
	.dragging .grip {
		opacity: 1;
		background: var(--color-accent);
	}
	.splitter:hover .line,
	.splitter:focus-visible .line,
	.dragging .line {
		width: var(--border-focus);
		background: var(--color-accent);
	}
	.splitter:focus-visible .grip {
		box-shadow: 0 0 0 var(--border-focus) var(--color-surface), 0 0 0 calc(var(--border-focus) * 2) var(--color-focus);
	}
	@media (prefers-reduced-motion: reduce) {
		.line,
		.grip {
			transition: none;
		}
	}
</style>
