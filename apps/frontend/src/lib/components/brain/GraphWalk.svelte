<!--
@component
The agent's walk through the company graph for one answer: every node and link its tool calls
touched, drawn as they arrive. Links carry the number of the step that found them; dashed links are
implied by the rows rather than stored in the graph. The starting node is ink at the centre. While a
step is the newest, its nodes wear an accent ring. Pass `highlight` (from a hovered citation or
ledger row) to dim everything that does not back it. `carried` is context from earlier questions
(`carryOver`): drawn dashed and faint until a step touches it. New links draw on from their ends;
when a step lands, nodes already drawn glide to their new places with their links (no jump).
Layout and rules live in `src/lib/walk.ts`.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import { NODE_LABELS, type NodeType, type WalkNode, type WalkRel, type WalkStep } from '$lib/types';
	import {
		STAGE,
		layoutWalk,
		mergeWalk,
		relKey,
		nodeType,
		pillHalfWidth,
		type Highlight,
		type Point
	} from '$lib/walk';

	type Props = {
		steps: WalkStep[];
		highlight?: Highlight | null;
		/** Ring the nodes of this step (the newest while the answer is still running). */
		fresh?: number | null;
		/** Nodes the answer cites: they keep their names when the walk is crowded. */
		cited?: ReadonlySet<string>;
		/** Context from earlier questions, drawn dashed (see `carryOver`). */
		carried?: { nodes: WalkNode[]; rels: WalkRel[] };
	};

	let { steps, highlight = null, fresh = null, cited = new Set(), carried }: Props = $props();

	/**
	 * Above this many nodes of its own, only the nodes that matter keep their names; the rest are
	 * dots. Carried nodes keep their names only while the whole walk is this small.
	 */
	const CROWDED = 12;

	const own = $derived(mergeWalk(steps));
	// The parent rebuilds `carried` whenever the thread grows (each new question). Keep the last one
	// while its content is the same, so a drawn walk is not laid out again and does not drift.
	const NONE: { nodes: WalkNode[]; rels: WalkRel[] } = { nodes: [], rels: [] };
	let kept = NONE;
	let keptKey = JSON.stringify(NONE);
	const context = $derived.by(() => {
		const next = carried ?? NONE;
		const key = JSON.stringify(next);
		if (key !== keptKey) {
			kept = next;
			keptKey = key;
		}
		return kept;
	});
	const ghosts = $derived(new Set(context.nodes.filter((n) => !own.nodes.some((o) => o.uid === n.uid)).map((n) => n.uid)));
	const walk = $derived.by(() => {
		if (ghosts.size === 0) return own;
		const extraNodes = context.nodes.filter((n) => ghosts.has(n.uid)).map((n) => ({ ...n, step: 0 }));
		const have = new Set(own.rels.map((r) => r.key));
		const extraRels = context.rels
			.map((r) => ({ ...r, step: 0, key: relKey(r) }))
			.filter((r) => !have.has(r.key) && (ghosts.has(r.from) || ghosts.has(r.to)));
		return { ...own, nodes: [...own.nodes, ...extraNodes], rels: [...own.rels, ...extraRels] };
	});
	const ghostRel = (r: { from: string; to: string }) => ghosts.has(r.from) || ghosts.has(r.to);
	// Positions from the last layout seed the next, so a new step adds to the picture.
	let previous: Map<string, Point> = new Map();
	const positions = $derived.by(() => {
		const titles = new Map(walk.nodes.map((n) => [n.uid, n.title]));
		const steps = new Map(walk.nodes.map((n) => [n.uid, n.step]));
		// Sized by what is named without a highlight, so hovering a citation never moves nodes.
		const next = layoutWalk(walk, previous, (uid) =>
			pillHalfWidth(named(uid, steps.get(uid) ?? 0, false) ? (titles.get(uid) ?? '') : null, MAX_TITLE)
		);
		previous = next;
		return next;
	});

	/** How long drawn nodes take to glide to a new layout. Matches --duration-slow (320ms): keep them in step. */
	const GLIDE_MS = 320;
	// Nodes and links read the same glided positions, so a link never jumps while its nodes move.
	let shown = $state.raw(new Map<string, Point>());
	$effect(() => {
		const target = positions;
		const from = untrack(() => shown);
		const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
		if (still || from.size === 0) {
			shown = target;
			return;
		}
		const t0 = performance.now();
		let frame = 0;
		const tick = (t: number) => {
			const k = Math.min(1, (t - t0) / GLIDE_MS);
			const e = 1 - (1 - k) ** 3;
			shown = new Map(
				[...target].map(([uid, p]) => {
					const a = from.get(uid) ?? p;
					return [uid, { x: a.x + (p.x - a.x) * e, y: a.y + (p.y - a.y) * e }];
				})
			);
			if (k < 1) frame = requestAnimationFrame(tick);
		};
		frame = requestAnimationFrame(tick);
		return () => cancelAnimationFrame(frame);
	});
	const at = (uid: string) => shown.get(uid) ?? positions.get(uid);
	const types = $derived([...new Set(walk.nodes.map((n) => nodeType(n.label)))] as NodeType[]);
	// Context from earlier questions never crowds this answer's own nodes into dots.
	const crowded = $derived(own.nodes.length > CROWDED);

	const pct = (p: Point | undefined, axis: 'x' | 'y') =>
		p ? `${(p[axis] / (axis === 'x' ? STAGE.width : STAGE.height)) * 100}%` : '50%';

	const freshRels = $derived(walk.rels.filter((r) => r.step === fresh).length);
	function showLabel(key: string, step: number): boolean {
		if (step === 0) return false; // context from an earlier question
		if (highlight) return highlight.rels.has(key);
		return walk.rels.length <= 10 || (step === fresh && freshRels <= 6);
	}
	function named(uid: string, step: number, lit = true): boolean {
		if (ghosts.has(uid)) return walk.nodes.length <= CROWDED;
		if (!crowded || uid === walk.focus) return true;
		if (lit && highlight) return highlight.nodes.has(uid);
		return step === fresh || cited.has(uid);
	}
	const MAX_TITLE = 26;
	const short = (t: string) => (t.length > MAX_TITLE ? `${t.slice(0, MAX_TITLE - 1)}…` : t);
</script>

<figure class="walk">
	<div class="canvas">
		{#if walk.nodes.length === 0}
			<p class="empty">The nodes the agent reads, and how they connect, appear here step by step.</p>
		{/if}
		<svg viewBox="0 0 {STAGE.width} {STAGE.height}" aria-hidden="true">
			{#each walk.rels as rel (rel.key)}
				{@const a = at(rel.from)}
				{@const b = at(rel.to)}
				{#if a && b}
					{@const lit = highlight?.rels.has(rel.key) ?? false}
					{@const ghost = ghostRel(rel)}
					<line
						x1={a.x}
						y1={a.y}
						x2={b.x}
						y2={b.y}
						pathLength={rel.inferred || ghost ? undefined : 1}
						class={[
							'edge',
							{
								inferred: rel.inferred,
								ghost,
								draw: !rel.inferred && !ghost,
								lit,
								fresh: !highlight && rel.step === fresh,
								dim: highlight && !lit
							}
						]}
					/>
				{/if}
			{/each}
			{#each walk.rels as rel (rel.key)}
				{@const a = at(rel.from)}
				{@const b = at(rel.to)}
				{#if a && b && showLabel(rel.key, rel.step)}
					<text
						x={(a.x + b.x) / 2}
						y={(a.y + b.y) / 2 + 4}
						class={['label', { lit: highlight?.rels.has(rel.key) }]}
						text-anchor="middle">{rel.step} · {rel.note ?? rel.type}</text
					>
				{/if}
			{/each}
		</svg>
		{#each walk.nodes as node (node.uid)}
			{@const p = at(node.uid)}
			{@const type = nodeType(node.label)}
			<svelte:element
				this={node.url ? 'a' : 'span'}
				href={node.url ?? undefined}
				target={node.url ? '_blank' : undefined}
				rel={node.url ? 'noreferrer' : undefined}
				class={[
					'node',
					{
						compact: !named(node.uid, node.step),
						focus: node.uid === walk.focus,
						ghost: ghosts.has(node.uid),
						fresh: !highlight && node.step === fresh,
						lit: highlight?.nodes.has(node.uid),
						dim: highlight && !highlight.nodes.has(node.uid)
					}
				]}
				style:left={pct(p, 'x')}
				style:top={pct(p, 'y')}
				style:--node="var(--node-{type})"
				title={ghosts.has(node.uid)
					? `${NODE_LABELS[type]}: ${node.title} (found by an earlier question)`
					: `${NODE_LABELS[type]}: ${node.title} (step ${node.step})`}
				aria-label={ghosts.has(node.uid)
					? `${NODE_LABELS[type]}: ${node.title}, found by an earlier question`
					: `${NODE_LABELS[type]}: ${node.title}, found in step ${node.step}`}
			>
				<span class="dot" aria-hidden="true"></span>
				<span class="sr-only">{NODE_LABELS[type]}:</span>
				<span class="name">{short(node.title)}</span>
			</svelte:element>
		{/each}
	</div>
	{#if walk.nodes.length}
		<figcaption>
			<span class="count tabular">{own.nodes.length} nodes · {own.rels.length} links</span>
			<ul class="legend" aria-label="Node types">
				{#each types as type (type)}
					<li style:--node="var(--node-{type})"><span class="dot" aria-hidden="true"></span>{NODE_LABELS[type]}</li>
				{/each}
				<li class="key"><span class="dash" aria-hidden="true"></span>Implied by the rows</li>
				{#if ghosts.size}<li class="key"><span class="ghost-key" aria-hidden="true"></span>From an earlier question</li>{/if}
			</ul>
		</figcaption>
	{/if}
</figure>

<style>
	.walk {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin: 0;
		min-width: 0;
	}
	.canvas {
		position: relative;
		aspect-ratio: 640 / 420;
		width: 100%;
	}
	svg {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		overflow: visible;
	}
	.empty {
		position: absolute;
		inset: 0;
		display: grid;
		place-items: center;
		padding: var(--space-8);
		color: var(--color-text-muted);
		text-align: center;
	}
	.edge {
		stroke: var(--graph-edge);
		stroke-width: 1.5;
		vector-effect: non-scaling-stroke;
		transition: opacity var(--duration-base) var(--ease-out);
	}
	.edge.inferred {
		stroke-dasharray: 3 4;
	}
	/* A stored link draws on from its ends when it first appears (pathLength is 1). */
	.edge.draw {
		stroke-dasharray: 1;
		animation: draw var(--duration-slow) var(--ease-out);
	}
	.edge.ghost {
		stroke-dasharray: 2 5;
		opacity: 0.45;
	}
	.edge.fresh {
		stroke: var(--color-accent);
		stroke-width: 2;
	}
	.edge.lit {
		stroke: var(--color-accent);
		stroke-width: 2.5;
	}
	.edge.dim {
		opacity: 0.2;
	}
	.label {
		fill: var(--color-text-muted);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		paint-order: stroke;
		stroke: var(--color-surface);
		stroke-width: 5px;
		stroke-linejoin: round;
	}
	.label.lit {
		fill: var(--color-accent);
	}
	.node {
		position: absolute;
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		max-width: 12rem;
		padding: var(--space-1) var(--space-3) var(--space-1) var(--space-2);
		border: var(--border-hair) solid var(--color-line-strong);
		border-radius: var(--radius-full);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
		line-height: 1.4;
		text-decoration: none;
		white-space: nowrap;
		transform: translate(-50%, -50%);
		transition: opacity var(--duration-base) var(--ease-out);
		animation: appear var(--duration-base) var(--ease-out);
	}
	.node.ghost {
		border-style: dashed;
		background: var(--color-surface);
		color: var(--color-text-muted);
		opacity: 0.7;
	}
	a.node:hover {
		border-color: var(--node);
	}
	.node.focus {
		border-color: var(--color-text);
		background: var(--color-text);
		color: var(--color-surface);
		font-weight: var(--weight-semibold);
	}
	.node.fresh,
	.node.lit {
		border: var(--border-focus) solid var(--color-accent);
	}
	.node.fresh {
		box-shadow: 0 0 0 4px var(--color-accent-soft);
	}
	.node.dim {
		opacity: 0.25;
	}
	/* A crowded walk shows most nodes as dots; the name comes back on hover or focus. */
	.node.compact {
		padding: var(--space-1);
		z-index: 0;
	}
	.node.compact .name {
		display: none;
	}
	.node.compact:hover,
	.node.compact:focus-visible {
		z-index: 2;
		padding: var(--space-1) var(--space-3) var(--space-1) var(--space-2);
		opacity: 1;
	}
	.node.compact:hover .name,
	.node.compact:focus-visible .name {
		display: inline;
	}
	.node:not(.compact) {
		z-index: 1;
	}
	.dot {
		flex: none;
		width: 0.5rem;
		height: 0.5rem;
		border-radius: var(--radius-full);
		background: var(--node);
	}
	figcaption {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2) var(--space-4);
		color: var(--color-text-muted);
		font-size: var(--text-xs);
	}
	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1) var(--space-3);
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.legend li {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
	}
	.dash {
		width: 1rem;
		border-top: 1.5px dashed var(--graph-edge);
	}
	.ghost-key {
		width: 0.9rem;
		height: 0.6rem;
		border: 1px dashed var(--color-line-strong);
		border-radius: var(--radius-full);
	}
	/* A new node grows in where it lands. */
	@keyframes appear {
		from {
			opacity: 0;
			transform: translate(-50%, -50%) scale(0.85);
		}
	}
	@keyframes draw {
		from {
			stroke-dashoffset: 1;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.node,
		.edge {
			transition: none;
			animation: none;
		}
	}
</style>
