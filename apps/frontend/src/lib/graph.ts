/**
 * The Graph page's map (design direction D, "Territories") as pure functions: where each
 * territory and node sits, the territory outlines, the ink routes between territories, what a
 * selected node links to, which nodes the filters keep, and search.
 *
 * Why: the layout is the design. Its numbers come from the prototype the direction was picked
 * from: a territory's radius is 6.6·√size + 10 and the territories are packed side by side;
 * nodes are pulled to their territory's centre and kept inside it (which leaves the arcs along a
 * full territory's edge); a seeded random source makes the same graph draw the same map. Pure, so
 * it runs in a worker (`graphLayout.ts`) and in tests. Territories come from the backend
 * (apps/brain/brain/graph_view.py); this file only places them.
 */
import {
	forceCollide,
	forceLink,
	forceManyBody,
	forceSimulation,
	forceX,
	forceY,
	type SimulationLinkDatum,
	type SimulationNodeDatum
} from 'd3-force';
import { packSiblings } from 'd3-hierarchy';
import type { GraphLabel, GraphNode, GraphView } from './types';

/** The map's own coordinate space; the canvas scales it to fit. */
export const WORLD = { width: 968, height: 688 } as const;
/** Fewer links than this between two territories draw no route. */
export const ROUTE_MIN = 10;

export interface PlacedNode {
	uid: string;
	x: number;
	y: number;
	r: number;
}

export interface PlacedTerritory {
	id: string;
	/** The packed circle the territory's nodes are kept in. */
	x: number;
	y: number;
	r: number;
	/** The middle of its nodes, where routes start and end. */
	cx: number;
	cy: number;
	/** The top of its outline, where its name sits. */
	top: number;
	/** The outline drawn around its nodes, as SVG path data (canvas reads it with Path2D). */
	outline: string;
}

export interface MapLayout {
	width: number;
	height: number;
	/** What is drawn, with room for the territory names: the view fits this, not the whole map. */
	bounds: { x0: number; y0: number; x1: number; y1: number };
	/** In the order of `view.nodes`. */
	nodes: PlacedNode[];
	territories: PlacedTerritory[];
}

export interface Route {
	a: string;
	b: string;
	count: number;
	width: number;
	/** The curve, as SVG path data. */
	path: string;
}

/** A node's dot: bigger with more links; systems a little bigger than the rest. */
export function nodeRadius(label: GraphLabel, degree: number): number {
	return label === 'System'
		? Math.min(9, 2.8 + Math.sqrt(degree) * 0.3)
		: Math.min(8, 1.6 + Math.sqrt(degree) * 0.3);
}

/** The territory circle's radius before it is scaled to the map. */
export function territoryRadius(size: number): number {
	return 6.6 * Math.sqrt(size) + 10;
}

/** A small seeded random source (Park–Miller), so a layout is the same on every run. */
export function seeded(seed: number): () => number {
	let s = Math.max(1, Math.floor(seed)) % 2147483647;
	return () => (s = (s * 16807) % 2147483647) / 2147483647;
}

const round = (v: number) => Math.round(v * 10) / 10;

type Sim = SimulationNodeDatum & { uid: string; r: number; territory: string };

/** Place every territory and node of `view` in a `width` × `height` map. */
export function layoutMap(
	view: Pick<GraphView, 'nodes' | 'edges' | 'territories'>,
	{ width = WORLD.width, height = WORLD.height, ticks = 500, seed = 3 } = {}
): MapLayout {
	const circles = view.territories.map((t) => ({ id: t.id, r: territoryRadius(t.size), x: 0, y: 0 }));
	packSiblings(circles);
	const margin = 12;
	if (circles.length) {
		const x0 = Math.min(...circles.map((c) => c.x - c.r));
		const x1 = Math.max(...circles.map((c) => c.x + c.r));
		const y0 = Math.min(...circles.map((c) => c.y - c.r));
		const y1 = Math.max(...circles.map((c) => c.y + c.r));
		const k = Math.min((width - 2 * margin) / (x1 - x0), (height - 2 * margin) / (y1 - y0));
		const dx = margin + (width - 2 * margin - (x1 - x0) * k) / 2;
		const dy = margin + (height - 2 * margin - (y1 - y0) * k) / 2;
		for (const c of circles) {
			c.x = dx + (c.x - x0) * k;
			c.y = dy + (c.y - y0) * k;
			c.r *= k;
		}
	}
	const home = new Map(circles.map((c) => [c.id, c]));
	const centre = (n: { territory: string }) => home.get(n.territory) ?? { x: width / 2, y: height / 2, r: 0 };

	const rnd = seeded(seed);
	const sim: Sim[] = view.nodes.map((n) => {
		const c = centre(n);
		return {
			uid: n.uid,
			r: nodeRadius(n.label, n.degree),
			territory: n.territory,
			x: c.x + (rnd() - 0.5) * 80,
			y: c.y + (rnd() - 0.5) * 80
		};
	});
	const known = new Set(sim.map((n) => n.uid));
	const links: SimulationLinkDatum<Sim>[] = view.edges
		.filter((e) => known.has(e.source) && known.has(e.target))
		.map((e) => ({ source: e.source, target: e.target }));
	const simulation = forceSimulation(sim)
		.randomSource(rnd)
		.force(
			'link',
			forceLink<Sim, SimulationLinkDatum<Sim>>(links)
				.id((d) => d.uid)
				.distance(12)
				.strength(0.08)
		)
		.force('charge', forceManyBody<Sim>().strength(-6).distanceMax(120))
		.force('x', forceX<Sim>((d) => centre(d).x).strength(0.11))
		.force('y', forceY<Sim>((d) => centre(d).y).strength(0.11))
		.force('collide', forceCollide<Sim>((d) => d.r + 0.8))
		.stop();
	simulation.tick(ticks);

	for (const n of sim) {
		n.x = Math.max(12, Math.min(width - 12, n.x ?? 0));
		n.y = Math.max(12, Math.min(height - 12, n.y ?? 0));
		const c = home.get(n.territory);
		if (!c) continue;
		const dx = n.x - c.x;
		const dy = n.y - c.y;
		const l = Math.hypot(dx, dy);
		const m = c.r - 6;
		if (l > m && l > 0) {
			n.x = c.x + (dx / l) * m;
			n.y = c.y + (dy / l) * m;
		}
	}

	const points = new Map<string, [number, number][]>();
	for (const n of sim) {
		const list = points.get(n.territory) ?? [];
		list.push([n.x ?? 0, n.y ?? 0]);
		points.set(n.territory, list);
	}
	const xs = sim.map((n) => n.x ?? 0);
	const ys = sim.map((n) => n.y ?? 0);
	const bounds = xs.length
		? {
				x0: round(Math.min(...xs) - 40),
				y0: round(Math.min(...ys) - 40),
				x1: round(Math.max(...xs) + 40),
				y1: round(Math.max(...ys) + 24)
			}
		: { x0: 0, y0: 0, x1: width, y1: height };
	return {
		width,
		height,
		bounds,
		nodes: sim.map((n) => ({ uid: n.uid, x: round(n.x ?? 0), y: round(n.y ?? 0), r: round(n.r) })),
		territories: circles.map((c) => {
			const pts = points.get(c.id) ?? [];
			const cx = pts.length ? pts.reduce((sum, p) => sum + p[0], 0) / pts.length : c.x;
			const cy = pts.length ? pts.reduce((sum, p) => sum + p[1], 0) / pts.length : c.y;
			const top = pts.length ? Math.min(...pts.map((p) => p[1])) - 9 : c.y - c.r * 0.5;
			return {
				id: c.id,
				x: round(c.x),
				y: round(c.y),
				r: round(c.r),
				cx: round(cx),
				cy: round(cy),
				top: round(top),
				outline: pts.length >= 3 ? outline(pts, 9) : circlePath(c.x, c.y, Math.max(8, c.r * 0.5))
			};
		})
	};
}

/** The convex hull of `points`, counter-clockwise (Andrew's monotone chain). */
export function hull(points: [number, number][]): [number, number][] {
	const pts = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
	if (pts.length < 3) return pts;
	const cross = (o: number[], a: number[], b: number[]) =>
		(a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
	const lower: [number, number][] = [];
	for (const p of pts) {
		while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0)
			lower.pop();
		lower.push(p);
	}
	const upper: [number, number][] = [];
	for (const p of [...pts].reverse()) {
		while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0)
			upper.pop();
		upper.push(p);
	}
	return lower.slice(0, -1).concat(upper.slice(0, -1));
}

/** A smooth closed outline around `points`: the hull pushed out by `pad`, as a closed spline. */
export function outline(points: [number, number][], pad: number): string {
	const h = hull(points);
	if (h.length < 3) return circlePath(points[0]?.[0] ?? 0, points[0]?.[1] ?? 0, pad);
	const cx = h.reduce((s, p) => s + p[0], 0) / h.length;
	const cy = h.reduce((s, p) => s + p[1], 0) / h.length;
	const e = h.map(([x, y]) => {
		const dx = x - cx;
		const dy = y - cy;
		const l = Math.hypot(dx, dy) || 1;
		return [x + (dx / l) * pad, y + (dy / l) * pad];
	});
	const n = e.length;
	let d = '';
	for (let i = 0; i < n; i++) {
		const p0 = e[(i - 1 + n) % n];
		const p1 = e[i];
		const p2 = e[(i + 1) % n];
		const p3 = e[(i + 2) % n];
		if (i === 0) d += `M${round(p1[0])} ${round(p1[1])}`;
		d +=
			` C${round(p1[0] + (p2[0] - p0[0]) / 6)} ${round(p1[1] + (p2[1] - p0[1]) / 6)}` +
			` ${round(p2[0] - (p3[0] - p1[0]) / 6)} ${round(p2[1] - (p3[1] - p1[1]) / 6)}` +
			` ${round(p2[0])} ${round(p2[1])}`;
	}
	return d + 'Z';
}

function circlePath(x: number, y: number, r: number): string {
	return `M${round(x - r)} ${round(y)} a${round(r)} ${round(r)} 0 1 0 ${round(2 * r)} 0 a${round(r)} ${round(r)} 0 1 0 ${round(-2 * r)} 0Z`;
}

/** The ink routes: one curve per pair of territories with at least `ROUTE_MIN` links between them. */
export function routes(view: Pick<GraphView, 'nodes' | 'edges'>, layout: MapLayout): Route[] {
	const territory = new Map(view.nodes.map((n) => [n.uid, n.territory]));
	const counts = new Map<string, number>();
	for (const e of view.edges) {
		const a = territory.get(e.source);
		const b = territory.get(e.target);
		if (!a || !b || a === b) continue;
		const key = a < b ? `${a}\u0000${b}` : `${b}\u0000${a}`;
		counts.set(key, (counts.get(key) ?? 0) + 1);
	}
	const at = new Map(layout.territories.map((t) => [t.id, t]));
	const out: Route[] = [];
	for (const [key, count] of counts) {
		if (count < ROUTE_MIN) continue;
		const [a, b] = key.split('\u0000');
		const A = at.get(a);
		const B = at.get(b);
		if (!A || !B) continue;
		const mx = (A.cx + B.cx) / 2 + (B.cy - A.cy) * 0.15;
		const my = (A.cy + B.cy) / 2 - (B.cx - A.cx) * 0.15;
		out.push({
			a,
			b,
			count,
			width: Math.min(10, 0.8 + Math.log2(count)),
			path: `M${A.cx} ${A.cy} Q${round(mx)} ${round(my)} ${B.cx} ${B.cy}`
		});
	}
	// Thin first, so the thick routes are drawn on top.
	return out.sort((x, y) => x.count - y.count || (x.a + x.b < y.a + y.b ? -1 : 1));
}

export interface RelCount {
	rel: string;
	/** `out`: the selected node is the source. */
	direction: 'out' | 'in';
	label: GraphLabel;
	count: number;
}

export interface TerritoryCount {
	id: string;
	name: string;
	count: number;
}

export interface Neighbourhood {
	/** The node and every node it links to. */
	uids: Set<string>;
	links: number;
	/** Biggest first. */
	byRel: RelCount[];
	/** Distinct neighbours per territory, biggest first. */
	byTerritory: TerritoryCount[];
}

/** What `uid` links to in this view, counted for the inspector. */
export function neighbourhood(
	view: Pick<GraphView, 'nodes' | 'edges' | 'territories'>,
	uid: string
): Neighbourhood {
	const node = new Map(view.nodes.map((n) => [n.uid, n]));
	const uids = new Set<string>([uid]);
	const rel = new Map<string, RelCount>();
	let links = 0;
	for (const e of view.edges) {
		const out = e.source === uid;
		if (!out && e.target !== uid) continue;
		const other = node.get(out ? e.target : e.source);
		if (!other) continue;
		links++;
		uids.add(other.uid);
		const key = `${e.rel}|${out ? 'out' : 'in'}|${other.label}`;
		const entry = rel.get(key) ?? {
			rel: e.rel,
			direction: out ? 'out' : 'in',
			label: other.label,
			count: 0
		};
		entry.count++;
		rel.set(key, entry);
	}
	const names = new Map(view.territories.map((t) => [t.id, t.name]));
	const per = new Map<string, number>();
	for (const id of uids) {
		if (id === uid) continue;
		const t = node.get(id)?.territory;
		if (t) per.set(t, (per.get(t) ?? 0) + 1);
	}
	return {
		uids,
		links,
		byRel: [...rel.values()].sort((a, b) => b.count - a.count || a.rel.localeCompare(b.rel)),
		byTerritory: [...per]
			.map(([id, count]) => ({ id, name: names.get(id) ?? id, count }))
			.sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
	};
}

/** The nodes the filters keep: of a kept kind, and a bot only when bots are shown (the backend
 *  already leaves them out otherwise). Links need both ends kept and a kept relationship. */
export function kept(
	view: Pick<GraphView, 'nodes' | 'edges'>,
	kinds: ReadonlySet<GraphLabel>,
	rels: ReadonlySet<string>
): { nodes: Set<string>; edges: boolean[] } {
	const nodes = new Set(view.nodes.filter((n) => kinds.has(n.label)).map((n) => n.uid));
	return {
		nodes,
		edges: view.edges.map((e) => rels.has(e.rel) && nodes.has(e.source) && nodes.has(e.target))
	};
}

/** The name a node goes by on the map and in lists. */
export function nodeName(n: Pick<GraphNode, 'label' | 'title' | 'number' | 'uid'>): string {
	const title = n.title ?? n.uid;
	return n.label === 'WorkItem' && n.number != null ? `#${n.number} ${title}` : title;
}

/** Up to `limit` nodes matching `query` (name or #number): names that start with it first, then
 *  names that contain it; within each, the most linked first. */
export function search(view: Pick<GraphView, 'nodes'>, query: string, limit = 8): GraphNode[] {
	const q = query.trim().toLowerCase().replace(/^#/, '');
	if (!q) return [];
	const scored: [number, GraphNode][] = [];
	for (const n of view.nodes) {
		const title = (n.title ?? '').toLowerCase();
		const number = n.number != null ? String(n.number) : '';
		const rank = title.startsWith(q) || number === q ? 0 : title.includes(q) ? 1 : -1;
		if (rank >= 0) scored.push([rank, n]);
	}
	return scored
		.sort((a, b) => a[0] - b[0] || b[1].degree - a[1].degree || a[1].uid.localeCompare(b[1].uid))
		.slice(0, limit)
		.map(([, n]) => n);
}

/** Counts per kind and relationship, for the filter panel. */
export function tally(view: Pick<GraphView, 'nodes' | 'edges'>) {
	const kinds = new Map<GraphLabel, number>();
	for (const n of view.nodes) kinds.set(n.label, (kinds.get(n.label) ?? 0) + 1);
	const rels = new Map<string, number>();
	for (const e of view.edges) rels.set(e.rel, (rels.get(e.rel) ?? 0) + 1);
	const byCount = <K>(m: Map<K, number>) => [...m].sort((a, b) => b[1] - a[1]);
	return { kinds: byCount(kinds), rels: byCount(rels) };
}
