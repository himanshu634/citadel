<!--
@component
One question on the Ask page (direction J + L) and everything it led to, as one lane: a strip
across the top (`Q<n>`, the question, how it went), then the conversation on the left (the question
as a message, the brain's ledger of steps, the answer or why there is none, and Copy answer, the
thumbs and Replay walk) and that question's own walk on the right, sticky while the lane scrolls
by. Use it once per turn of an `AskThread`; the page owns the columns (`walkWidth`), the splitter
and the scrolling. Hovering a citation or a ledger row lights what backs it in the walk (a
citation wins). The walk is first drawn when the lane comes near the screen (`root` is the scroll
container) and then stays drawn, so it never lays out or animates again; until then a box of the
same size keeps its place. Folded, the walk cell shows a dot and the node count, and a drawn walk
is only hidden, so it opens where it was. While the answer runs, a hidden live region tells
screen readers the step under way. Below 1100px the walk goes under the conversation.
-->
<script lang="ts">
	import { Copy, LoaderCircle, RotateCcw, Waypoints } from '@lucide/svelte';
	import { untrack } from 'svelte';
	import type { Attachment } from 'svelte/attachments';
	import type { Turn } from '$lib/ask.svelte';
	import type { Rating, WalkStep } from '$lib/types';
	import { answerPlainText, carryOver, highlightFor, mergeWalk, progressLine, stepHighlight } from '$lib/walk';
	import Banner from '../ui/Banner.svelte';
	import Button from '../ui/Button.svelte';
	import AnswerRating from './AnswerRating.svelte';
	import GraphWalk from './GraphWalk.svelte';
	import TurnTimeline from './TurnTimeline.svelte';
	import WalkAnswer from './WalkAnswer.svelte';
	import WalkLedger from './WalkLedger.svelte';

	type Props = {
		turn: Turn;
		/** Its place in the thread, from 0 (shown as Q1). */
		index: number;
		/** The company's name: the reply is signed "<brain> brain". */
		brain: string;
		/** The steps of every earlier question, for the walk's context (`carryOver`). */
		earlier?: WalkStep[];
		/** The walk column's CSS width; the same for every lane. */
		walkWidth: string;
		/** The walk column is folded to its strip. */
		folded?: boolean;
		/** The scroll container the lane sits in (the viewport when absent). */
		root?: HTMLElement | null;
		/** At least this tall, in px (the newest lane: room to scroll its top to the top). */
		minHeight?: number | null;
		/** While replaying this lane: how many graph steps are shown. */
		revealed?: number | null;
		replaying?: boolean;
		onreplay?: () => void;
		/** A thumbs (or null, taken back), with the note sent with a thumbs down. */
		onrate?: (rating: Rating | null, note?: string) => void;
	};

	let {
		turn,
		index,
		brain,
		earlier = [],
		walkWidth,
		folded = false,
		root = null,
		minHeight = null,
		revealed = null,
		replaying = false,
		onreplay,
		onrate
	}: Props = $props();
	const id = $props.id();

	/** How long "Copied" (or "Couldn't copy") stays on the button. */
	const COPY_SAID_MS = 2000;

	let active = $state<number | null>(null);
	let pinned = $state<number | null>(null);
	let open = $state<string | null>(null);
	/** The ledger row under the pointer, and whether the answer was running when it was hovered. */
	let hovered = $state<{ steps: WalkStep[]; running: boolean } | null>(null);
	/** The walk has been near the screen once: from then on it stays drawn. */
	let drawn = $state(false);
	let copied = $state<'idle' | 'copied' | 'failed'>('idle');
	// An answer that arrives while the lane watches fades in; one that was already there does not.
	const live = untrack(() => turn.status === 'running');

	const n = $derived(index + 1);
	const running = $derived(turn.status === 'running');
	const shown = $derived(revealed === null ? turn.steps : turn.steps.filter((s) => s.n !== null && s.n <= revealed));
	const graphSteps = $derived(turn.steps.filter((s) => s.n !== null).length);
	const nodes = $derived(mergeWalk(turn.steps).nodes.length);
	const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? '' : 's'}`;
	const meta = $derived(
		running
			? 'working'
			: turn.status === 'stopped'
				? 'stopped'
				: turn.status === 'failed'
					? 'failed'
					: `${plural(graphSteps, 'step')} · ${plural(nodes, 'node')}`
	);

	const lit = $derived(active ?? pinned);
	// When the answer lands, rows fold into groups under a still pointer (no mouseleave): a hover
	// from before that no longer counts.
	const hoveredSteps = $derived(hovered?.running === running ? hovered.steps : null);
	const highlight = $derived.by(() => {
		const src = lit === null ? undefined : turn.answer?.sources[lit - 1];
		if (src) return highlightFor(src, turn.steps);
		if (!hoveredSteps) return null;
		return stepHighlight({
			nodes: hoveredSteps.flatMap((s) => s.nodes ?? []),
			rels: hoveredSteps.flatMap((s) => s.rels ?? [])
		});
	});
	/** For screen readers, what the running answer is doing now. */
	const progress = $derived(running ? progressLine(turn.steps) : '');
	const cites = $derived.by(() => {
		const map = new Map<string, number[]>();
		turn.answer?.sources.forEach((s, i) => map.set(s.uid, [...(map.get(s.uid) ?? []), i + 1]));
		return map;
	});
	const cited = $derived(new Set(turn.answer?.sources.map((s) => s.uid) ?? []));
	const fresh = $derived.by(() => {
		if (!running) return null;
		// The first step is the whole picture so far: nothing to tell apart yet.
		const last = turn.steps.filter((s) => s.n !== null && s.status === 'done').at(-1)?.n ?? null;
		return last !== null && last > 1 ? last : null;
	});
	const carried = $derived(carryOver(earlier, shown));

	let copyTimer: ReturnType<typeof setTimeout> | undefined;
	async function copy() {
		const text = turn.answer?.text;
		if (!text) return;
		try {
			await navigator.clipboard.writeText(answerPlainText(text));
			copied = 'copied';
		} catch {
			copied = 'failed';
		}
		clearTimeout(copyTimer);
		copyTimer = setTimeout(() => (copied = 'idle'), COPY_SAID_MS);
	}
	$effect(() => () => clearTimeout(copyTimer));

	/** Draw the walk the first time the lane is within 200px of the scroll container's view. */
	function nearScreen(within: HTMLElement | null): Attachment<HTMLElement> {
		return (el) => {
			const io = new IntersectionObserver(
				([entry]) => {
					if (!entry.isIntersecting) return;
					drawn = true;
					io.disconnect();
				},
				{ root: within, rootMargin: '200px' }
			);
			io.observe(el);
			return () => io.disconnect();
		};
	}
</script>

<article
	class={['lane', { folded }]}
	data-lane={index}
	aria-labelledby="{id}-q"
	style:--walk-width={walkWidth}
	style:min-height={minHeight ? `${minHeight}px` : undefined}
>
	<header class="strip">
		<h2 id="{id}-q" class="title">
			<span class="qn">Q{n}</span>
			<span class="question" title={turn.question}>{turn.question}</span>
		</h2>
		<p class="meta tabular">{meta}</p>
	</header>

	<div class="chat">
		<!-- The strip's heading already says the question to assistive tech. -->
		<p class="bubble" aria-hidden="true">{turn.question}</p>
		<div class="who">
			<span class="mark" aria-hidden="true"><Waypoints /></span>
			<span class="name">{brain} brain</span>
			<span class="status tabular" aria-live="polite">
				{#if running}<LoaderCircle class="spin" aria-hidden="true" />working{:else}{plural(graphSteps, 'step')}{/if}
			</span>
			<!-- Always there, so the first step is announced too; empty unless the answer runs. -->
			<span class="sr-only" role="status" aria-live="polite">{progress}</span>
		</div>
		<WalkLedger
			steps={shown}
			settled={!running}
			{open}
			ontoggle={(key) => (open = open === key ? null : key)}
			onhover={(steps) => (hovered = steps && { steps, running })}
			{cites}
			active={lit}
		/>
		{#if turn.answer}
			<WalkAnswer
				answer={turn.answer}
				active={lit}
				{pinned}
				reveal={live}
				onactive={(c) => (active = c)}
				onpin={(c) => (pinned = pinned === c ? null : c)}
			/>
		{:else if turn.error}
			<Banner tone="danger" title="This answer failed">{turn.error}</Banner>
		{:else if turn.status === 'stopped'}
			<p class="note">You stopped this answer. The steps it took are kept above.</p>
		{/if}
		{#if !running}
			<div class="actions">
				{#if turn.answer?.text}
					<Button size="sm" variant="ghost" onclick={copy}>
						<Copy aria-hidden="true" />{copied === 'copied' ? 'Copied' : copied === 'failed' ? "Couldn't copy" : 'Copy answer'}
					</Button>
				{/if}
				{#if turn.answer?.trace_id && turn.answer.stop !== 'stopped'}
					<AnswerRating
						rating={turn.rating}
						note={turn.note}
						status={turn.rated}
						onrate={(r) => onrate?.(r)}
						onnote={(text) => onrate?.('down', text)}
					/>
				{/if}
				<Button size="sm" variant="ghost" disabled={graphSteps === 0} onclick={() => onreplay?.()}>
					<RotateCcw aria-hidden="true" />{replaying ? 'Replaying' : 'Replay walk'}
				</Button>
			</div>
		{/if}
		{#if turn.calls.length}
			<!-- Folded under one line: the ledger already shows the work as it happens. -->
			<TurnTimeline calls={turn.calls} steps={turn.steps} />
		{/if}
	</div>

	<div class="walk" {@attach nearScreen(root)}>
		{#if folded}
			<p class={['marker', turn.status]}>
				<span class="dot" aria-hidden="true"></span>
				<span class="count tabular" aria-hidden="true">{nodes}</span>
				<span class="sr-only">Q{n} walk: {plural(nodes, 'node')}, {meta}</span>
			</p>
		{/if}
		<!-- Folded, the card is hidden, not removed: the drawn walk keeps its layout and its
		     finished animations (display: none would replay them on unfold). -->
		<section class={['card', { away: folded }]} aria-labelledby="{id}-walk">
			<h3 id="{id}-walk" class="card-head">
				<span>Q{n} walk</span>
				<span class="meta tabular">{plural(nodes, 'node')}</span>
			</h3>
			{#if drawn}
				<GraphWalk steps={shown} {highlight} {fresh} {cited} {carried} />
			{:else}
				<div class="placeholder" aria-hidden="true">
					<div class="placeholder-canvas"></div>
					{#if nodes}<div class="placeholder-caption"></div>{/if}
				</div>
			{/if}
		</section>
	</div>
</article>

<style>
	.lane {
		display: grid;
		grid-template-columns: minmax(0, 1fr) var(--splitter-hit) var(--walk-width);
		grid-template-rows: auto 1fr;
		grid-template-areas:
			'strip strip strip'
			'chat . walk';
		animation: rise var(--duration-base) var(--ease-out);
	}
	.strip {
		grid-area: strip;
		display: flex;
		align-items: baseline;
		gap: var(--space-3);
		min-width: 0;
		padding: var(--space-2) var(--space-6);
		border-top: var(--border-hair) solid var(--color-line);
	}
	.title {
		display: flex;
		flex: 1;
		align-items: baseline;
		gap: var(--space-3);
		min-width: 0;
		font-size: var(--text-sm);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	.qn {
		flex: none;
		color: var(--color-text-muted);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
		font-variation-settings: normal;
	}
	.question {
		overflow: hidden;
		min-width: 0;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.meta {
		flex: none;
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.chat {
		grid-area: chat;
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		width: 100%;
		max-width: 46rem;
		min-width: 0;
		padding: var(--space-6);
	}
	.bubble {
		align-self: flex-end;
		max-width: 85%;
		padding: var(--space-3) var(--space-4);
		border-radius: var(--radius-md) var(--radius-md) var(--radius-sm) var(--radius-md);
		background: var(--color-accent-soft);
		color: var(--color-text);
		font-size: var(--text-lg);
		line-height: var(--leading-ui);
		overflow-wrap: anywhere;
	}
	.who {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.mark {
		display: grid;
		flex: none;
		place-items: center;
		width: calc(var(--space-6) + var(--space-1));
		height: calc(var(--space-6) + var(--space-1));
		border-radius: var(--radius-full);
		background: var(--color-text);
		color: var(--color-surface);
	}
	.mark :global(svg) {
		width: var(--space-4);
		height: var(--space-4);
	}
	.name {
		font-size: var(--text-md);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	.status {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.status :global(svg) {
		width: var(--space-3);
		height: var(--space-3);
		color: var(--color-accent);
	}
	.note {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2) var(--space-3);
	}
	.walk {
		grid-area: walk;
		min-width: 0;
		padding: var(--space-3);
	}
	.card {
		position: sticky;
		top: var(--space-3);
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-3);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}
	.card-head {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
		font-size: var(--text-sm);
		font-weight: var(--weight-semibold);
		font-variation-settings: 'wdth' var(--width-label);
	}
	.card.away {
		visibility: hidden;
		height: 0;
		padding: 0;
		overflow: hidden;
	}
	/* GraphWalk's box: its canvas, then (once there are nodes) one caption line. */
	.placeholder {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.placeholder-canvas {
		aspect-ratio: 640 / 420;
		width: 100%;
	}
	.placeholder-caption {
		height: calc(var(--text-xs) * var(--leading-ui));
	}
	.folded .walk {
		padding-inline: 0;
	}
	.marker {
		position: sticky;
		top: var(--space-3);
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-1);
		padding-top: var(--space-2);
	}
	.dot {
		width: var(--space-2);
		height: var(--space-2);
		border-radius: var(--radius-full);
		background: var(--color-success);
	}
	.marker.running .dot {
		background: var(--color-accent);
		box-shadow: 0 0 0 var(--space-1) var(--color-accent-soft);
	}
	.marker.failed .dot {
		background: var(--color-danger);
	}
	.marker.stopped .dot {
		background: var(--color-text-muted);
	}
	.count {
		color: var(--color-text-muted);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}
	@keyframes rise {
		from {
			opacity: 0;
			transform: translateY(var(--space-2));
		}
	}
	@media (max-width: 1100px) {
		.lane {
			grid-template-columns: minmax(0, 1fr);
			grid-template-rows: auto;
			grid-template-areas:
				'strip'
				'chat'
				'walk';
		}
		.strip,
		.chat {
			padding-inline: var(--space-4);
		}
		.walk {
			padding: 0 var(--space-4) var(--space-6);
		}
		.card {
			position: static;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.lane {
			animation: none;
		}
	}
</style>
