/**
 * Getting a map layout for a graph view: in a Web Worker when the browser has one, and cached,
 * so coming back to the Graph page draws at once.
 *
 * Why: `layoutMap` takes seconds on a real company (2,272 nodes on brain_falkordb), and the same
 * view always gives the same layout. The cache is keyed by slug, the bots switch and the view's
 * content, so a sync that changes the graph lays it out again.
 */
import { layoutMap, type MapLayout } from './graph';
import type { GraphView } from './types';

export const TICKS = 300;

const cache = new Map<string, MapLayout>();
let worker: Worker | null = null;
let next = 0;
const waiting = new Map<number, (layout: MapLayout) => void>();

/** The view's content, not just its size: a sync can change uids or territories and keep the
 *  counts, and a layout drawn for other nodes would put them in the wrong places. */
function keyOf(view: GraphView): string {
	let h = 5381;
	const mix = (text: string) => {
		for (let i = 0; i < text.length; i++) h = ((h << 5) + h + text.charCodeAt(i)) | 0;
	};
	for (const n of view.nodes) mix(`${n.uid}|${n.territory}|${n.degree};`);
	return `${view.slug}|${view.bots_shown}|${view.nodes.length}|${view.edges.length}|${h >>> 0}`;
}

function getWorker(): Worker | null {
	if (worker || typeof Worker === 'undefined') return worker;
	worker = new Worker(new URL('./graph.worker.ts', import.meta.url), { type: 'module' });
	worker.onmessage = (event: MessageEvent<{ id: number; layout: MapLayout }>) => {
		waiting.get(event.data.id)?.(event.data.layout);
		waiting.delete(event.data.id);
	};
	return worker;
}

/** The cached layout of `view`, if it was laid out before. */
export function cachedLayout(view: GraphView): MapLayout | null {
	return cache.get(keyOf(view)) ?? null;
}

/** Lay out `view` (in the worker when there is one). */
export function computeLayout(view: GraphView): Promise<MapLayout> {
	const key = keyOf(view);
	const hit = cache.get(key);
	if (hit) return Promise.resolve(hit);
	const w = getWorker();
	const done = (layout: MapLayout) => {
		cache.set(key, layout);
		return layout;
	};
	if (!w) return Promise.resolve(done(layoutMap(view, { ticks: TICKS })));
	const id = ++next;
	return new Promise((resolve) => {
		waiting.set(id, (layout) => resolve(done(layout)));
		// A plain copy: the view may be a Svelte proxy, which cannot be cloned into a worker.
		w.postMessage({ id, view: JSON.parse(JSON.stringify(view)), ticks: TICKS });
	});
}
