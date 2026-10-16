<!--
@component
The agent's walk through the company graph for one answer: every node and link its tool calls
touched, drawn as they arrive. Links carry the number of the step that found them; dashed links are
implied by the rows rather than stored in the graph. The starting node is ink at the centre. While a
step is the newest, its nodes wear an accent ring. Pass `highlight` (from a hovered citation) to
dim everything that does not back it. Layout and rules live in `src/lib/walk.ts`.
-->
<script lang="ts">
	import { NODE_LABELS, type NodeType, type WalkStep } from '$lib/types';
	import {
		STAGE,
		layoutWalk,
		mergeWalk,
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
	};

	let { steps, highlight = null, fresh = null, cited = new Set() }: Props = $props();

	/** Above this many nodes, only the nodes that matter keep their names; the rest are dots. */
	const CROWDED = 12;

	const walk = $derived(mergeWalk(steps));
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
	const types = $derived([...new Set(walk.nodes.map((n) => nodeType(n.label)))] as NodeType[]);
	const crowded = $derived(walk.nodes.length > CROWDED);

	const pct = (p: Point | undefined, axis: 'x' | 'y') =>
		p ? `${(p[axis] / (axis === 'x' ? STAGE.width : STAGE.height)) * 100}%` : '50%';

	const freshRels = $derived(walk.rels.filter((r) => r.step === fresh).length);
	function showLabel(key: string, step: number): boolean {
		if (highlight) return highlight.rels.has(key);
		return walk.rels.length <= 10 || (step === fresh && freshRels <= 6);
	}
	function named(uid: string, step: number, lit = true): boolean {
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
				{@const a = positions.get(rel.from)}
				{@const b = positions.get(rel.to)}
				{#if a && b}
					{@const lit = highlight?.rels.has(rel.key) ?? false}
					<line
						x1={a.x}
						y1={a.y}
						x2={b.x}
						y2={b.y}
						class={['edge', { inferred: rel.inferred, lit, fresh: !highlight && rel.step === fresh, dim: highlight && !lit }]}
					/>
				{/if}
			{/each}
			{#each walk.rels as rel (rel.key)}
				{@const a = positions.get(rel.from)}
				{@const b = positions.get(rel.to)}
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
			{@const p = positions.get(node.uid)}
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
						fresh: !highlight && node.step === fresh,
						lit: highlight?.nodes.has(node.uid),
						dim: highlight && !highlight.nodes.has(node.uid)
					}
				]}
				style:left={pct(p, 'x')}
				style:top={pct(p, 'y')}
				style:--node="var(--node-{type})"
				title="{NODE_LABELS[type]}: {node.title} (step {node.step})"
			>
				<span class="dot" aria-hidden="true"></span>
				<span class="sr-only">{NODE_LABELS[type]}:</span>
				<span class="name">{short(node.title)}</span>
			</svelte:element>
		{/each}
	</div>
	{#if walk.nodes.length}
		<figcaption>
			<span class="count tabular">{walk.nodes.length} nodes · {walk.rels.length} links</span>
			<ul class="legend" aria-label="Node types">
				{#each types as type (type)}
					<li style:--node="var(--node-{type})"><span class="dot" aria-hidden="true"></span>{NODE_LABELS[type]}</li>
				{/each}
				<li class="key"><span class="dash" aria-hidden="true"></span>Implied by the rows</li>
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
		transition:
			left var(--duration-base) var(--ease-out),
			top var(--duration-base) var(--ease-out),
			opacity var(--duration-base) var(--ease-out);
		animation: appear var(--duration-base) var(--ease-out);
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
	@keyframes appear {
		from {
			opacity: 0;
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
