<!--
@component
The agent's walk through the company graph for one answer, played the way the agent walked it
(design direction P, "Follow the agent"). An accent mark moves to where each query starts: its
anchor (the system, person or node it asked about) or a spot of its own. Links grow out of it hop
by hop and each node appears when its link reaches it; a dashed route joins the places it read.
Steps play one at a time in `WALK_MS` each, however fast they arrive, and while a step's tool
still runs the mark waits at its anchor. A walk already there when the component mounts is drawn
at rest; one that shrinks (a replay) starts again. Links carry the number of the step that found
them; dashed links are implied by the rows. The first node is ink, anchors wear an ink ring. Pass
`highlight` (a hovered citation or ledger row) to dim everything that does not back it. `carried`
is context from earlier questions, drawn dashed and faint. Reduced motion: each step appears
whole. Layout and timing live in `src/lib/walk.ts`.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import { NODE_LABELS, type NodeType, type WalkNode, type WalkRel, type WalkStep } from '$lib/types';
	import {
		STAGE,
		WALK_MS,
		growSchedule,
		layoutFollow,
		mergeWalk,
		relKey,
		relTypesLine,
		nodeType,
		pillHalfWidth,
		stepAnchor,
		stepSentence,
		type Highlight,
		type Point
	} from '$lib/walk';

	type Props = {
		steps: WalkStep[];
		highlight?: Highlight | null;
		/** The newest step while the answer is still running: its nodes keep their names. */
		fresh?: number | null;
		/** Nodes the answer cites: they keep their names when the walk is crowded. */
		cited?: ReadonlySet<string>;
		/** Context from earlier questions, drawn dashed (see `carryOver`). */
		carried?: { nodes: WalkNode[]; rels: WalkRel[] };
		/** The answer is still running: the mark stays on stage between steps. */
		working?: boolean;
	};

	let { steps, highlight = null, fresh = null, cited = new Set(), carried, working = false }: Props = $props();

	/**
	 * Above this many nodes of its own, only the nodes that matter keep their names; the rest are
	 * dots. Carried nodes keep their names only while the whole walk is this small.
	 */
	const CROWDED = 12;
	const MAX_TITLE = 26;
	/** How far the stage may lean in on a small step. */
	const MAX_ZOOM = 1.45;

	const graph = $derived(steps.filter((s) => s.n !== null));
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
	// Context from earlier questions never crowds this answer's own nodes into dots.
	const crowded = $derived(own.nodes.length > CROWDED);
	const anchors = $derived(
		new Set(graph.map((s) => stepAnchor(s)).filter((u): u is string => !!u && own.nodes.some((n) => n.uid === u)))
	);

	// --- playing the steps one at a time ---------------------------------------------------------
	const still = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
	/** Graph steps fully shown. A walk already there at mount is shown at rest. */
	let played = $state(untrack(() => graph.length));
	/** ms into the step in play (graph[played]). */
	let clock = $state(0);
	$effect.pre(() => {
		const n = graph.length;
		if (untrack(() => played) > n) {
			played = n; // a replay emptied the walk: play it again from the start
			clock = 0;
		}
	});
	const playing = $derived(played < graph.length ? graph[played] : null);
	const empty = (s: WalkStep) => (s.nodes ?? []).length === 0;
	const length = (s: WalkStep) => WALK_MS.call + (empty(s) ? WALK_MS.empty : WALK_MS.grow) + WALK_MS.settle;
	$effect(() => {
		const step = playing;
		if (!step) return;
		if (still()) {
			played = graph.length;
			clock = 0;
			return;
		}
		// While the tool still runs the mark waits at the anchor; the step grows once rows are in.
		const waiting = step.status === 'running';
		const total = length(step);
		const t0 = performance.now() - untrack(() => clock);
		let frame = 0;
		const tick = (t: number) => {
			const ms = t - t0;
			if (waiting) clock = Math.min(ms, WALK_MS.call);
			else if (ms >= total) {
				clock = 0;
				played += 1;
				return;
			} else clock = ms;
			frame = requestAnimationFrame(tick);
		};
		frame = requestAnimationFrame(tick);
		return () => cancelAnimationFrame(frame);
	});

	// --- where things are ------------------------------------------------------------------------
	function named(uid: string, step: number, lit = true): boolean {
		if (ghosts.has(uid)) return walk.nodes.length <= CROWDED;
		if (!crowded || uid === walk.focus || anchors.has(uid)) return true;
		if (lit && highlight) return highlight.nodes.has(uid);
		return step === fresh || cited.has(uid);
	}
	const short = (t: string) => (t.length > MAX_TITLE ? `${t.slice(0, MAX_TITLE - 1)}…` : t);
	// Sized by what is named without a highlight, so hovering a citation never moves nodes.
	const halfWidth = $derived.by(() => {
		const byUid = new Map(walk.nodes.map((n) => [n.uid, n]));
		return (uid: string) => {
			const n = byUid.get(uid);
			return pillHalfWidth(n && named(uid, n.step, false) ? n.title : null, MAX_TITLE);
		};
	});
	// The layout of the steps shown, and of those plus the step in play.
	const before = $derived(layoutFollow(graph.slice(0, played), halfWidth, context));
	const after = $derived(playing ? layoutFollow(graph.slice(0, played + 1), halfWidth, context) : before);
	const indexOf = $derived(new Map(graph.map((s, i) => [s.n, i])));
	const drawn = $derived(new Set(graph.slice(0, played).flatMap((s) => (s.nodes ?? []).map((n) => n.uid))));
	const growth = $derived(playing && !empty(playing) ? growSchedule(playing, drawn) : null);
	const linkGrowth = $derived(new Map((growth?.links ?? []).map((l) => [l.key, l])));
	const ease = (k: number) => 1 - (1 - Math.min(1, Math.max(0, k))) ** 3;
	const glide = $derived(ease(clock / WALK_MS.call));
	const grown = $derived(clock - WALK_MS.call);
	const settling = $derived(
		playing ? Math.min(1, Math.max(0, (clock - length(playing) + WALK_MS.settle) / WALK_MS.settle)) : 1
	);
	function at(uid: string): Point | undefined {
		const b = after.pos.get(uid);
		const a = before.pos.get(uid);
		if (!b) return a;
		if (!a || !playing) return b;
		return { x: a.x + (b.x - a.x) * glide, y: a.y + (b.y - a.y) * glide };
	}
	/** 0..1: how far a node has appeared. */
	function shown(uid: string, step: number): number {
		if (step === 0) return 1; // context from an earlier question
		const i = indexOf.get(step) ?? 0;
		if (i < played) return 1;
		if (!playing || i > played) return 0;
		const t = growth?.arrive.get(uid);
		return t === undefined ? 0 : Math.min(1, Math.max(0, (grown - t) / 160));
	}
	/** 0..1: how far a link has grown, and the end it grows from. */
	function reach(key: string, step: number): { k: number; src: string | null } {
		if (step === 0) return { k: 1, src: null };
		const i = indexOf.get(step) ?? 0;
		if (i < played) return { k: 1, src: null };
		if (!playing || i > played) return { k: 0, src: null };
		const l = linkGrowth.get(key);
		if (!l) return { k: 0, src: null };
		return { k: ease((grown - l.t0) / (l.t1 - l.t0)), src: l.src };
	}

	// The mark: where the agent is looking.
	const spotOf = (s: WalkStep | undefined, l: typeof after) => (s && s.n !== null ? l.spots.get(s.n) : undefined);
	const mark = $derived.by((): Point | null => {
		if (playing) {
			const to = spotOf(playing, after);
			if (!to) return null;
			const from = spotOf(graph[played - 1], before) ?? to;
			return { x: from.x + (to.x - from.x) * glide, y: from.y + (to.y - from.y) * glide };
		}
		if (!working) return null;
		return spotOf(graph.at(-1), before) ?? { x: STAGE.width / 2, y: STAGE.height / 2 };
	});
	const spokes = $derived(
		(growth?.spokes ?? []).map((s) => ({ ...s, k: ease((grown - s.t0) / (s.t1 - s.t0)) })).filter((s) => s.k > 0 && grown < s.t1 + 500)
	);
	const route = $derived.by(() => {
		const pts: Point[] = [];
		graph.slice(0, played + (playing ? 1 : 0)).forEach((s, i) => {
			if (empty(s)) return;
			const p = spotOf(s, i < played ? before : after);
			if (p && !pts.some((q) => q.x === p.x && q.y === p.y)) pts.push(p);
		});
		if (playing && !empty(playing) && mark && pts.length) pts[pts.length - 1] = mark;
		return pts;
	});
	const chip = $derived.by(() => {
		if (!playing) return null;
		const done = playing.status !== 'running';
		const sentence = stepSentence(playing, done);
		if (!done) return sentence;
		if (empty(playing)) {
			if (playing.error) return `${sentence}: it failed`;
			return playing.count ? `${sentence}: counts only, nothing to draw` : `${sentence}: nothing found`;
		}
		const rels = playing.rels ?? [];
		return grown > WALK_MS.grow * 0.5 && rels.length ? `${sentence} · ${relTypesLine(rels)}` : sentence;
	});

	// The stage leans in on a small step while it plays, and back out as it settles.
	const camera = $derived.by(() => {
		const home = { x: STAGE.width / 2, y: STAGE.height / 2, z: 1 };
		if (!playing || empty(playing)) return home;
		const pts = (playing.nodes ?? []).map((n) => after.pos.get(n.uid)).filter((p): p is Point => !!p);
		if (pts.length < 2) return home;
		const xs = pts.map((p) => p.x);
		const ys = pts.map((p) => p.y);
		const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
		const z = Math.min(MAX_ZOOM, STAGE.width / (x1 - x0 + 200), STAGE.height / (y1 - y0 + 90));
		if (z < 1.1) return home;
		const k = Math.min(glide, 1 - settling);
		return {
			x: home.x + ((x0 + x1) / 2 - home.x) * k,
			y: home.y + ((y0 + y1) / 2 - home.y) * k,
			z: 1 + (z - 1) * k
		};
	});
	const lens = $derived(
		camera.z === 1
			? undefined
			: `translate(${(0.5 - (camera.x / STAGE.width) * camera.z) * 100}%, ${(0.5 - (camera.y / STAGE.height) * camera.z) * 100}%) scale(${camera.z})`
	);

	const types = $derived([...new Set(walk.nodes.map((n) => nodeType(n.label)))] as NodeType[]);
	const pct = (p: Point | undefined, axis: 'x' | 'y') =>
		p ? `${(p[axis] / (axis === 'x' ? STAGE.width : STAGE.height)) * 100}%` : '50%';

	const freshRels = $derived(walk.rels.filter((r) => r.step === fresh).length);
	function showLabel(key: string, step: number): boolean {
		if (step === 0) return false; // context from an earlier question
		if (reach(key, step).k < 1) return false;
		if (highlight) return highlight.rels.has(key);
		return walk.rels.length <= 10 || (step === fresh && freshRels <= 6);
	}
	/** The step in play, until it settles: its links and nodes wear the accent. */
	const live = (step: number) => playing !== null && playing.n === step && settling < 0.5;
</script>

<figure class="walk">
	<div class="canvas">
		{#if walk.nodes.length === 0 && !mark}
			<p class="empty">The nodes the agent reads, and how they connect, appear here step by step.</p>
		{/if}
		<div class="lens" style:transform={lens}>
			<svg viewBox="0 0 {STAGE.width} {STAGE.height}" aria-hidden="true">
				{#each walk.rels as rel (rel.key)}
					{@const grow = reach(rel.key, rel.step)}
					{@const p = at(rel.from)}
					{@const q = at(rel.to)}
					{#if p && q && grow.k > 0}
						{@const a = grow.src === rel.to ? q : p}
						{@const b = grow.src === rel.to ? p : q}
						{@const lit = highlight?.rels.has(rel.key) ?? false}
						<line
							x1={a.x}
							y1={a.y}
							x2={a.x + (b.x - a.x) * grow.k}
							y2={a.y + (b.y - a.y) * grow.k}
							class={[
								'edge',
								{
									inferred: rel.inferred,
									ghost: ghostRel(rel),
									lit,
									live: !highlight && live(rel.step),
									dim: highlight && !lit
								}
							]}
						/>
					{/if}
				{/each}
				{#if mark}
					{#each spokes as s (s.uid)}
						{@const b = at(s.uid)}
						{#if b}
							<line
								class="spoke"
								x1={mark.x}
								y1={mark.y}
								x2={mark.x + (b.x - mark.x) * s.k}
								y2={mark.y + (b.y - mark.y) * s.k}
							/>
						{/if}
					{/each}
				{/if}
				{#if route.length > 1}
					<polyline class={['route', { dim: highlight }]} points={route.map((p) => `${p.x},${p.y}`).join(' ')} />
				{/if}
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
				{@const k = shown(node.uid, node.step)}
				{#if k > 0}
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
								anchor: anchors.has(node.uid) && node.uid !== walk.focus,
								ghost: ghosts.has(node.uid),
								fresh: !highlight && live(node.step),
								lit: highlight?.nodes.has(node.uid),
								dim: highlight && !highlight.nodes.has(node.uid)
							}
						]}
						style:left={pct(p, 'x')}
						style:top={pct(p, 'y')}
						style:opacity={k < 1 ? k : undefined}
						style:scale={k < 1 ? 0.7 + 0.3 * k : undefined}
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
				{/if}
			{/each}
			{#if mark}
				<span
					class={['mark', { searching: playing && empty(playing) && !playing.count && grown > 0 }]}
					style:left={pct(mark, 'x')}
					style:top={pct(mark, 'y')}
					aria-hidden="true"
				></span>
				{#if chip}
					<span class="chip" style:left={pct(mark, 'x')} style:top={pct(mark, 'y')} style:opacity={1 - settling} aria-hidden="true"
						>{chip}</span
					>
				{/if}
			{/if}
		</div>
	</div>
	{#if walk.nodes.length}
		<figcaption>
			<span class="count tabular">{own.nodes.length} nodes · {own.rels.length} links</span>
			<ul class="legend" aria-label="Node types">
				{#each types as type (type)}
					<li style:--node="var(--node-{type})"><span class="dot" aria-hidden="true"></span>{NODE_LABELS[type]}</li>
				{/each}
				<li class="key"><span class="dash" aria-hidden="true"></span>Implied by the rows</li>
				{#if route.length > 1}<li class="key"><span class="route-key" aria-hidden="true"></span>The agent's route</li>{/if}
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
		overflow: hidden;
	}
	/* Everything on the stage, so the camera moves it as one. */
	.lens {
		position: absolute;
		inset: 0;
		transform-origin: 0 0;
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
		transition:
			opacity var(--duration-base) var(--ease-out),
			stroke var(--duration-slow) var(--ease-out);
	}
	.edge.inferred {
		stroke-dasharray: 3 4;
	}
	.edge.ghost {
		stroke-dasharray: 2 5;
		opacity: 0.45;
	}
	.edge.live {
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
	/* A node no link reaches (a list, a search) comes in on a spoke from the mark. */
	.spoke {
		stroke: var(--color-accent);
		stroke-width: 1;
		stroke-dasharray: 2 4;
		opacity: 0.5;
		vector-effect: non-scaling-stroke;
	}
	/* The places the agent read, joined in the order it read them. */
	.route {
		fill: none;
		stroke: var(--color-accent);
		stroke-width: 2.5;
		stroke-dasharray: 8 6;
		stroke-linejoin: round;
		opacity: 0.7;
		vector-effect: non-scaling-stroke;
		transition: opacity var(--duration-base) var(--ease-out);
	}
	.route.dim {
		opacity: 0.15;
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
	/* A place the agent started a query from. */
	.node.anchor {
		border: var(--border-focus) solid var(--color-text);
		font-weight: var(--weight-semibold);
	}
	.node.fresh,
	.node.lit {
		border: var(--border-focus) solid var(--color-accent);
	}
	.node.fresh:not(.compact) {
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
	/* Where the agent is looking: an accent dot that pulses while it works. It sits under the
	   named nodes, so on an anchor the pulse rings the pill instead of covering its name. */
	.mark {
		position: absolute;
		z-index: 0;
		width: 0.75rem;
		height: 0.75rem;
		border: var(--border-focus) solid var(--color-surface);
		border-radius: var(--radius-full);
		background: var(--color-accent);
		transform: translate(-50%, -50%);
		pointer-events: none;
	}
	.mark::after {
		content: '';
		position: absolute;
		inset: -0.25rem;
		border: var(--border-focus) solid var(--color-accent);
		border-radius: var(--radius-full);
		animation: pulse 1.1s var(--ease-out) infinite;
	}
	.mark.searching::after {
		border-color: var(--color-warning);
		animation-duration: 0.7s;
	}
	.chip {
		position: absolute;
		z-index: 3;
		max-width: 22rem;
		overflow: hidden;
		padding: var(--space-1) var(--space-3);
		border-radius: var(--radius-full);
		background: var(--color-accent-soft);
		color: var(--color-accent);
		font-size: var(--text-xs);
		font-weight: var(--weight-semibold);
		text-overflow: ellipsis;
		white-space: nowrap;
		transform: translate(-50%, 1.1rem);
		pointer-events: none;
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
	.route-key {
		width: 1rem;
		border-top: 2px dashed var(--color-accent);
	}
	.ghost-key {
		width: 0.9rem;
		height: 0.6rem;
		border: 1px dashed var(--color-line-strong);
		border-radius: var(--radius-full);
	}
	@keyframes pulse {
		from {
			opacity: 0.6;
			transform: scale(0.8);
		}
		to {
			opacity: 0;
			transform: scale(4);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.node,
		.edge,
		.route {
			transition: none;
		}
		.mark::after {
			animation: none;
			opacity: 0;
		}
	}
</style>
