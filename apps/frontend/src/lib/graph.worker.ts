/// <reference lib="webworker" />
/**
 * Lays out the Graph page's map off the main thread. Why: placing about 2,300 nodes takes a few
 * seconds, which would freeze the page. One message in (the view), one message out (the layout).
 */
import { layoutMap } from './graph';
import type { GraphView } from './types';

self.onmessage = (event: MessageEvent<{ id: number; view: GraphView; ticks: number }>) => {
	const { id, view, ticks } = event.data;
	self.postMessage({ id, layout: layoutMap(view, { ticks }) });
};
