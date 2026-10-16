<!--
@component
The whole company graph as a map of territories (design direction D): every node sits in the
territory of the system it touches most, territories are tonal areas, ink routes count the links
between them. Drag to pan, scroll or use the buttons to zoom, click a node to select it. A
selection lights the node's neighbours and links and dims everything else, and outlines the
territories it reaches in ink.

Why a canvas: thousands of nodes and links are too many for DOM elements. Labels are an HTML
layer on top, so they use the wide type. The canvas is hidden from assistive tech, which reads a
summary instead; the page's search and list are the keyboard way in (see design-system.md, Graph).
-->
<script lang="ts">
	import { Maximize, Minus, Plus } from '@lucide/svelte';
	import { quadtree } from 'd3-quadtree';
	import { untrack } from 'svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import { neighbourhood, nodeName, routes, type MapLayout, type PlacedNode } from '$lib/graph';
	import { LABEL_TYPES, NODE_LABELS, type GraphLabel, type GraphView } from '$lib/types';

	type Props = {
		view: GraphView;
		layout: MapLayout;
		/** The selected node's uid. */
		selected?: string | null;
		/** Nodes and links the filters keep; everything when not given. */
		keep?: { nodes: Set<string>; edges: boolean[] } | null;
		onselect?: (uid: string | null) => void;
		/** Scroll zooms the map. Off where the map sits inside a scrolling page; the buttons stay. */
		scrollZoom?: boolean;
	};

	let { view, layout, selected = null, keep = null, onselect, scrollZoom = true }: Props = $props();

	let canvas = $state<HTMLCanvasElement>();
	let size = $state({ width: 0, height: 0 });
	/** Where the user moved the map to; null shows the whole map, fitted to the box. */
	let moved = $state<{ k: number; x: number; y: number } | null>(null);
	let hover = $state<string | null>(null);
	let palette = $state<Record<string, string>>({});

	const index = $derived(new Map(view.nodes.map((n, i) => [n.uid, i])));
	/** Positions by uid, so a layout is never read by a node's place in the list. */
	const pos = $derived(new Map(layout.nodes.map((n) => [n.uid, n])));
	const shown = $derived(keep?.nodes ?? null);
	const keptView = $derived(
		keep ? { nodes: view.nodes, edges: view.edges.filter((_, i) => keep.edges[i]) } : view
	);
	const roads = $derived(routes(keptView, layout));
	const hood = $derived(selected ? neighbourhood({ ...keptView, territories: view.territories }, selected) : null);
	const reached = $derived(
		hood ? new Set(view.nodes.filter((n) => hood.uids.has(n.uid)).map((n) => n.territory)) : null
	);
	const finder = $derived(
		quadtree<PlacedNode>()
			.x((d) => d.x)
			.y((d) => d.y)
			.addAll(layout.nodes.filter((n) => !shown || shown.has(n.uid)))
	);
	const names = $derived(new Map(view.territories.map((t) => [t.id, t])));
	const summary = $derived(
		`Map of ${view.nodes.length.toLocaleString('en')} nodes in ${view.territories.length} territories.` +
			' Use Find or List to pick a node.'
	);

	/** The whole map, fitted to the box. Screen = world × k + (x, y). */
	const fitted = $derived.by(() => {
		const { x0, y0, x1, y1 } = layout.bounds;
		const k = Math.min(size.width / (x1 - x0), size.height / (y1 - y0)) || 1;
		return {
			k,
			x: (size.width - (x1 - x0) * k) / 2 - x0 * k,
			y: (size.height - (y1 - y0) * k) / 2 - y0 * k
		};
	});
	const transform = $derived(moved ?? fitted);

	function fit() {
		moved = null;
	}

	// A node picked outside the map (search, list, inspector) is brought into view, also after
	// the box changes size (the inspector opening narrows it).
	$effect(() => {
		const uid = selected;
		const { width, height } = size;
		if (!uid || !width || !height) return;
		untrack(() => {
			const n = pos.get(uid);
			if (!n) return;
			const sx = n.x * transform.k + transform.x;
			const sy = n.y * transform.k + transform.y;
			const pad = 48;
			if (sx < pad || sy < pad || sx > width - pad || sy > height - pad) {
				moved = { k: transform.k, x: width / 2 - n.x * transform.k, y: height / 2 - n.y * transform.k };
			}
		});
	});

	function readPalette(el: HTMLElement) {
		const css = getComputedStyle(el);
		const v = (name: string) => css.getPropertyValue(name).trim();
		palette = {
			surface: v('--color-surface'),
			ink: v('--color-text'),
			line: v('--color-line'),
			edge: v('--graph-edge'),
			t1: v('--graph-territory'),
			t2: v('--graph-territory-alt'),
			Person: v('--node-person'),
			Team: v('--node-team'),
			System: v('--node-system'),
			WorkItem: v('--node-work-item'),
			Change: v('--node-change'),
			Document: v('--node-document')
		};
	}

	/** Watch the box's size and the theme (the toggle sets html[data-theme]; the OS can too). */
	function watch(el: HTMLDivElement) {
		readPalette(el);
		const sizer = new ResizeObserver(([entry]) => {
			size = { width: entry.contentRect.width, height: entry.contentRect.height };
		});
		sizer.observe(el);
		const theme = new MutationObserver(() => readPalette(el));
		theme.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
		const media = matchMedia('(prefers-color-scheme: dark)');
		const onMedia = () => readPalette(el);
		media.addEventListener('change', onMedia);
		return () => {
			sizer.disconnect();
			theme.disconnect();
			media.removeEventListener('change', onMedia);
		};
	}

	let frame = 0;
	$effect(() => {
		// Read everything the drawing depends on, then draw once per animation frame.
		const deps = [canvas, size.width, size.height, transform, palette, view, layout, pos, shown, keptView, roads, hood, reached, hover, selected];
		void deps;
		cancelAnimationFrame(frame);
		frame = requestAnimationFrame(draw);
		return () => cancelAnimationFrame(frame);
	});

	function draw() {
		if (!canvas || !size.width || !palette.ink) return;
		const dpr = window.devicePixelRatio || 1;
		canvas.width = Math.round(size.width * dpr);
		canvas.height = Math.round(size.height * dpr);
		const ctx = canvas.getContext('2d');
		if (!ctx) return;
		ctx.setTransform(1, 0, 0, 1, 0, 0);
		ctx.fillStyle = palette.surface;
		ctx.fillRect(0, 0, canvas.width, canvas.height);
		const { k, x, y } = transform;
		ctx.setTransform(dpr * k, 0, 0, dpr * k, dpr * x, dpr * y);
		const dim = hood !== null;

		// Territories: alternating tones; "not linked to code" is only a dashed outline.
		layout.territories.forEach((t, i) => {
			const path = new Path2D(t.outline);
			const on = reached?.has(t.id) ?? false;
			ctx.globalAlpha = dim && !on ? 0.45 : 1;
			if (t.id !== 'none') {
				ctx.fillStyle = i % 2 ? palette.t2 : palette.t1;
				ctx.fill(path);
			}
			ctx.setLineDash(t.id === 'none' ? [5 / k, 4 / k] : []);
			ctx.strokeStyle = dim && on ? palette.ink : palette.line;
			ctx.lineWidth = (dim && on ? 1.4 : 1) / k;
			ctx.stroke(path);
		});
		ctx.setLineDash([]);
		ctx.globalAlpha = 1;

		// Links inside a territory: thin and quiet.
		const territory = (uid: string) => view.nodes[index.get(uid) ?? -1]?.territory;
		const at = (uid: string) => pos.get(uid);
		ctx.strokeStyle = palette.edge;
		ctx.lineWidth = 0.5;
		ctx.globalAlpha = dim ? 0.05 : 0.16;
		ctx.beginPath();
		for (const e of keptView.edges) {
			if (territory(e.source) !== territory(e.target)) continue;
			const a = at(e.source);
			const b = at(e.target);
			if (!a || !b) continue;
			ctx.moveTo(a.x, a.y);
			ctx.lineTo(b.x, b.y);
		}
		ctx.stroke();

		// Routes between territories: ink, as wide as the links they carry.
		ctx.strokeStyle = palette.ink;
		ctx.lineCap = 'round';
		ctx.globalAlpha = dim ? 0.07 : 0.22;
		for (const r of roads) {
			ctx.lineWidth = r.width;
			ctx.stroke(new Path2D(r.path));
		}
		ctx.lineCap = 'butt';

		// The selection's own links.
		if (selected && hood) {
			const s = at(selected);
			ctx.globalAlpha = 0.45;
			ctx.lineWidth = 0.7;
			ctx.beginPath();
			for (const e of keptView.edges) {
				if (e.source !== selected && e.target !== selected) continue;
				const o = at(e.source === selected ? e.target : e.source);
				if (!s || !o) continue;
				ctx.moveTo(s.x, s.y);
				ctx.lineTo(o.x, o.y);
			}
			ctx.stroke();
		}

		// Nodes, small first so hubs sit on top.
		const order = view.nodes
			.filter((v) => (!shown || shown.has(v.uid)) && pos.has(v.uid))
			.map((v) => [v.label, pos.get(v.uid)!] as const)
			.sort((a, b) => a[1].r - b[1].r);
		for (const [label, n] of order) {
			ctx.globalAlpha = dim && !hood?.uids.has(n.uid) ? 0.18 : 1;
			ctx.fillStyle = palette[label] ?? palette.ink;
			ctx.beginPath();
			ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
			ctx.fill();
		}
		ctx.globalAlpha = 1;

		for (const [uid, width, gap] of [
			[hover, 1.5, 3],
			[selected, 2.5, 4]
		] as const) {
			const n = uid ? at(uid) : null;
			if (!n) continue;
			ctx.strokeStyle = palette.ink;
			ctx.lineWidth = width / k;
			ctx.beginPath();
			ctx.arc(n.x, n.y, n.r + gap / k + 1, 0, Math.PI * 2);
			ctx.stroke();
		}
	}

	function worldAt(event: PointerEvent | WheelEvent) {
		const rect = canvas!.getBoundingClientRect();
		const sx = event.clientX - rect.left;
		const sy = event.clientY - rect.top;
		return { sx, sy, wx: (sx - transform.x) / transform.k, wy: (sy - transform.y) / transform.k };
	}

	function nodeAt(event: PointerEvent): string | null {
		const { wx, wy } = worldAt(event);
		return finder.find(wx, wy, 10 / transform.k)?.uid ?? null;
	}

	let drag: { x: number; y: number; tx: number; ty: number; moved: boolean } | null = null;

	function onpointerdown(event: PointerEvent) {
		canvas!.setPointerCapture(event.pointerId);
		drag = { x: event.clientX, y: event.clientY, tx: transform.x, ty: transform.y, moved: false };
	}

	function onpointermove(event: PointerEvent) {
		if (drag) {
			const dx = event.clientX - drag.x;
			const dy = event.clientY - drag.y;
			if (Math.hypot(dx, dy) > 4) drag.moved = true;
			if (drag.moved) {
				moved = { k: transform.k, x: drag.tx + dx, y: drag.ty + dy };
			}
			return;
		}
		hover = nodeAt(event);
	}

	function onpointerup(event: PointerEvent) {
		const was = drag;
		drag = null;
		if (was && !was.moved) onselect?.(nodeAt(event));
	}

	function zoomBy(factor: number, sx = size.width / 2, sy = size.height / 2) {
		const base = fitted.k;
		const k = Math.max(base * 0.6, Math.min(base * 12, transform.k * factor));
		const f = k / transform.k;
		moved = { k, x: sx - (sx - transform.x) * f, y: sy - (sy - transform.y) * f };
	}

	/** Scroll zooms around the pointer; the listener is not passive, so the page does not scroll. */
	function wheel(el: HTMLCanvasElement) {
		const onwheel = (event: WheelEvent) => {
			if (!scrollZoom && !event.ctrlKey) return; // a pinch arrives as ctrl + wheel
			event.preventDefault();
			const { sx, sy } = worldAt(event);
			zoomBy(Math.exp(-event.deltaY * 0.0015), sx, sy);
		};
		el.addEventListener('wheel', onwheel, { passive: false });
		return () => el.removeEventListener('wheel', onwheel);
	}

	const screen = (wx: number, wy: number) => ({
		left: wx * transform.k + transform.x,
		top: wy * transform.k + transform.y
	});
	const hovered = $derived(hover && hover !== selected ? view.nodes[index.get(hover) ?? -1] : null);
	const picked = $derived(selected ? view.nodes[index.get(selected) ?? -1] : null);
	const kindOf = (label: GraphLabel) => NODE_LABELS[LABEL_TYPES[label]];
</script>

<div class="map" {@attach watch}>
	<p class="sr-only">{summary}</p>
	<canvas
		bind:this={canvas}
		aria-hidden="true"
		class={{ pointing: hover !== null }}
		{onpointerdown}
		{onpointermove}
		{onpointerup}
		onpointerleave={() => (hover = null)}
		{@attach wheel}
	></canvas>

	<div class="labels" aria-hidden="true">
		{#each layout.territories as t (t.id)}
			{@const info = names.get(t.id)}
			{@const p = screen(t.cx, t.top)}
			{#if info && t.r * transform.k > 22}
				<span
					class={['territory', { small: t.r * transform.k < 48, faded: reached && !reached.has(t.id) }]}
					style:left="{p.left}px"
					style:top="{p.top}px"
				>
					{info.name}
					{#if t.r * transform.k >= 48}<small>{info.size.toLocaleString('en')}</small>{/if}
				</span>
			{/if}
		{/each}
		{#if hovered}
			{@const n = pos.get(hovered.uid)}
			{@const p = n ? screen(n.x, n.y) : { left: -999, top: -999 }}
			<span class="node hover" style:left="{p.left + 10}px" style:top="{p.top - 9}px">
				{nodeName(hovered)}<small>{kindOf(hovered.label)}</small>
			</span>
		{/if}
		{#if picked}
			{@const n = pos.get(picked.uid)}
			{@const p = n ? screen(n.x, n.y) : { left: -999, top: -999 }}
			<span class="node selected" style:left="{p.left + 12}px" style:top="{p.top - 9}px">
				{nodeName(picked)}
			</span>
		{/if}
	</div>

	<div class="zoom">
		<Button variant="secondary" size="sm" iconOnly label="Zoom in" onclick={() => zoomBy(1.4)}><Plus /></Button>
		<Button variant="secondary" size="sm" iconOnly label="Zoom out" onclick={() => zoomBy(1 / 1.4)}><Minus /></Button>
		<Button variant="secondary" size="sm" iconOnly label="Fit the map" onclick={fit}><Maximize /></Button>
	</div>
</div>

<style>
	.map {
		position: relative;
		width: 100%;
		height: 100%;
		min-height: 20rem;
		overflow: hidden;
		background: var(--color-surface);
	}
	canvas {
		display: block;
		width: 100%;
		height: 100%;
		cursor: grab;
		touch-action: none;
	}
	canvas.pointing {
		cursor: pointer;
	}
	canvas:active {
		cursor: grabbing;
	}
	canvas:focus-visible {
		outline: var(--border-focus) solid var(--color-focus);
		outline-offset: calc(-1 * var(--border-focus));
	}
	.labels {
		position: absolute;
		inset: 0;
		pointer-events: none;
	}
	.territory {
		position: absolute;
		/* Sits on the outline's top edge; the halo keeps it readable over dots and routes. */
		transform: translate(-50%, -70%);
		text-shadow:
			0 0 2px var(--color-surface),
			0 0 4px var(--color-surface),
			0 0 6px var(--color-surface);
		display: flex;
		flex-direction: column;
		align-items: center;
		color: var(--color-text);
		font-size: var(--text-sm);
		font-weight: var(--weight-black);
		font-variation-settings: 'wdth' var(--width-brand);
		line-height: var(--leading-tight);
		text-align: center;
		white-space: nowrap;
	}
	.territory small {
		color: var(--color-text-muted);
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
		font-variation-settings: 'wdth' var(--width-body);
	}
	.territory.small {
		font-size: var(--text-xs);
		font-weight: var(--weight-bold);
	}
	.territory.faded {
		opacity: 0.5;
	}
	.node {
		position: absolute;
		display: inline-flex;
		align-items: baseline;
		gap: var(--space-2);
		max-width: 22rem;
		padding: 0 var(--space-1);
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
		font-weight: var(--weight-bold);
		font-variation-settings: 'wdth' var(--width-label);
		line-height: 1.5;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.node.hover {
		background: var(--color-surface-raised);
		box-shadow: var(--shadow-overlay);
		color: var(--color-text);
	}
	.node small {
		color: var(--color-text-muted);
		font-weight: var(--weight-medium);
	}
	.node.selected {
		background: var(--color-text);
		color: var(--color-surface);
	}
	.zoom {
		position: absolute;
		right: var(--space-4);
		bottom: var(--space-4);
		display: flex;
		gap: var(--space-1);
	}
</style>
