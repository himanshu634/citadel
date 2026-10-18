import { describe, expect, it } from 'vitest';
import {
	edgesAt,
	hull,
	kept,
	layoutMap,
	neighbourhood,
	nodeName,
	nodeRadius,
	outline,
	propRows,
	ROUTE_MIN,
	routes,
	search,
	seeded,
	tally
} from './graph';
import type { GraphEdge, GraphLabel, GraphNode, GraphView, Territory } from './types';

function node(uid: string, label: GraphLabel, territory: string, extra: Partial<GraphNode> = {}): GraphNode {
	return {
		uid,
		label,
		title: uid,
		kind: null,
		state: null,
		number: null,
		url: null,
		is_bot: false,
		comments: 0,
		degree: 0,
		territory,
		...extra
	};
}

const territories: Territory[] = [
	{ id: 'system:auth', name: 'Auth', system_uid: 'system:auth', size: 4, systems: 1 },
	{ id: 'system:web', name: 'Web', system_uid: 'system:web', size: 3, systems: 1 },
	{ id: 'none', name: 'Not linked to code', system_uid: null, size: 1, systems: 0 }
];
const nodes: GraphNode[] = [
	node('system:auth', 'System', 'system:auth', { title: 'Auth', degree: 3 }),
	node('pr:1', 'WorkItem', 'system:auth', { title: 'Switch sessions to JWT', number: 1, degree: 3 }),
	node('change:1', 'Change', 'system:auth', { degree: 2 }),
	node('person:ana', 'Person', 'system:auth', { title: 'ana', degree: 2 }),
	node('system:web', 'System', 'system:web', { title: 'Web', degree: 1 }),
	node('pr:2', 'WorkItem', 'system:web', { title: 'Login page uses JWT', number: 22, degree: 2 }),
	node('doc:1', 'Document', 'system:web', { degree: 0 }),
	node('issue:9', 'WorkItem', 'none', { title: 'Docs typo', number: 9 })
];
const edges: GraphEdge[] = [
	{ source: 'change:1', rel: 'TOUCHES', target: 'system:auth' },
	{ source: 'change:1', rel: 'PART_OF', target: 'pr:1' },
	{ source: 'pr:1', rel: 'MENTIONS', target: 'system:auth' },
	{ source: 'person:ana', rel: 'AUTHORED', target: 'pr:1' },
	{ source: 'person:ana', rel: 'REVIEWED', target: 'pr:2' },
	{ source: 'pr:2', rel: 'MENTIONS', target: 'system:web' }
];
const view: GraphView = { slug: 't', nodes, edges, territories, bots: 0, bots_shown: false, comments: 0 };

describe('layoutMap', () => {
	const layout = layoutMap(view, { ticks: 200 });

	it('places every node, in the order of the view', () => {
		expect(layout.nodes.map((n) => n.uid)).toEqual(nodes.map((n) => n.uid));
		for (const n of layout.nodes) {
			expect(n.x).toBeGreaterThanOrEqual(12);
			expect(n.x).toBeLessThanOrEqual(layout.width - 12);
			expect(n.y).toBeGreaterThanOrEqual(12);
			expect(n.y).toBeLessThanOrEqual(layout.height - 12);
		}
	});

	it('keeps each node inside its territory', () => {
		const at = new Map(layout.territories.map((t) => [t.id, t]));
		layout.nodes.forEach((n, i) => {
			const t = at.get(nodes[i].territory)!;
			expect(Math.hypot(n.x - t.x, n.y - t.y)).toBeLessThanOrEqual(t.r - 6 + 0.11);
		});
	});

	it('packs territories without overlap and sizes them by count', () => {
		const [auth, web, none] = layout.territories;
		expect(auth.r).toBeGreaterThan(web.r);
		expect(web.r).toBeGreaterThan(none.r);
		expect(Math.hypot(auth.x - web.x, auth.y - web.y)).toBeGreaterThanOrEqual(auth.r + web.r - 0.5);
	});

	it('draws the same map every time', () => {
		expect(layoutMap(view, { ticks: 200 })).toEqual(layout);
	});

	it('outlines a territory with three or more nodes as a closed curve', () => {
		expect(layout.territories[0].outline).toMatch(/^M.* C.*Z$/);
	});

	it('handles an empty graph', () => {
		const empty = layoutMap({ nodes: [], edges: [], territories: [] });
		expect(empty.nodes).toEqual([]);
		expect(empty.territories).toEqual([]);
	});
});

describe('shapes', () => {
	it('sizes dots by links, systems a little bigger', () => {
		expect(nodeRadius('Person', 0)).toBe(1.6);
		expect(nodeRadius('System', 0)).toBe(2.8);
		expect(nodeRadius('Person', 10_000)).toBe(8);
		expect(nodeRadius('System', 10_000)).toBe(9);
	});

	it('finds the convex hull', () => {
		const square: [number, number][] = [
			[0, 0],
			[2, 0],
			[2, 2],
			[0, 2],
			[1, 1]
		];
		expect(hull(square)).toHaveLength(4);
		expect(outline(square, 5)).toMatch(/Z$/);
	});

	it('repeats the same random numbers for the same seed', () => {
		const a = seeded(3);
		const b = seeded(3);
		expect([a(), a()]).toEqual([b(), b()]);
	});
});

describe('routes', () => {
	it('draws a route only between territories with enough links', () => {
		const layout = layoutMap(view, { ticks: 50 });
		expect(routes(view, layout)).toEqual([]); // one link crosses Auth and Web
		const many = {
			nodes,
			edges: [
				...edges,
				...Array.from({ length: ROUTE_MIN }, (_, i) => ({
					source: 'pr:1',
					rel: `R${i}`,
					target: 'pr:2'
				}))
			]
		};
		const [route] = routes(many, layout);
		expect(route).toMatchObject({ a: 'system:auth', b: 'system:web', count: ROUTE_MIN + 1 });
		expect(route.path).toMatch(/^M.* Q/);
	});
});

describe('neighbourhood', () => {
	it('counts links by relationship and neighbours by territory', () => {
		const ana = neighbourhood(view, 'person:ana');
		expect(ana.links).toBe(2);
		expect([...ana.uids].sort()).toEqual(['person:ana', 'pr:1', 'pr:2']);
		expect(ana.byRel).toEqual([
			{ rel: 'AUTHORED', direction: 'out', label: 'WorkItem', count: 1 },
			{ rel: 'REVIEWED', direction: 'out', label: 'WorkItem', count: 1 }
		]);
		expect(ana.byTerritory).toEqual([
			{ id: 'system:auth', name: 'Auth', count: 1 },
			{ id: 'system:web', name: 'Web', count: 1 }
		]);
	});

	it('marks links that point at the node as in', () => {
		const pr = neighbourhood(view, 'pr:1');
		expect(pr.byRel.find((r) => r.rel === 'AUTHORED')).toMatchObject({ direction: 'in', label: 'Person' });
	});
});

describe('filters and search', () => {
	it('keeps nodes of kept kinds and links of kept relationships between them', () => {
		const k = kept(view, new Set<GraphLabel>(['Person', 'WorkItem']), new Set(['AUTHORED']));
		expect([...k.nodes].sort()).toEqual(['issue:9', 'person:ana', 'pr:1', 'pr:2']);
		expect(k.edges).toEqual([false, false, false, true, false, false]);
	});

	it('finds names that start with the query first, and #numbers', () => {
		expect(search(view, 'jwt').map((n) => n.uid)).toEqual(['pr:1', 'pr:2']);
		expect(search(view, 'login').map((n) => n.uid)).toEqual(['pr:2']);
		expect(search(view, '#22').map((n) => n.uid)).toEqual(['pr:2']);
		expect(search(view, '  ')).toEqual([]);
	});

	it('names work items with their number', () => {
		expect(nodeName(nodes[1])).toBe('#1 Switch sessions to JWT');
		expect(nodeName(nodes[3])).toBe('ana');
	});

	it('counts kinds and relationships, biggest first', () => {
		const t = tally(view);
		expect(t.kinds[0]).toEqual(['WorkItem', 3]);
		expect(t.rels.find(([r]) => r === 'MENTIONS')).toEqual(['MENTIONS', 2]);
	});
});

describe('edgesAt', () => {
	const at = (uid: string) =>
		({ a: { x: 0, y: 0 }, b: { x: 10, y: 0 }, c: { x: 0, y: 10 } })[uid as 'a' | 'b' | 'c'];
	const edges = [
		{ source: 'a', target: 'b' },
		{ source: 'a', target: 'c' },
		{ source: 'b', target: 'a' }
	];
	const all = () => true;

	it('finds every link between the nearest pair, either way round', () => {
		expect(edgesAt(edges, all, at, 5, 0.5, 2)).toEqual([0, 2]);
		expect(edgesAt(edges, all, at, 0.5, 6, 2)).toEqual([1]);
	});

	it('finds nothing beyond the tolerance or past a line end', () => {
		expect(edgesAt(edges, all, at, 5, 4, 2)).toEqual([]);
		expect(edgesAt(edges, all, at, 14, 0, 2)).toEqual([]);
	});

	it('looks only at drawn links', () => {
		expect(edgesAt(edges, (i) => i === 1, at, 5, 0.5, 2)).toEqual([]);
		expect(edgesAt(edges, (i) => i !== 2, at, 5, 0.5, 2)).toEqual([0]);
	});
});

describe('propRows', () => {
	it('puts uid first, then sorts by name', () => {
		expect(propRows({ title: 't', body: 'b', uid: 'u' }).map((r) => r.key)).toEqual([
			'uid',
			'body',
			'title'
		]);
	});

	it('writes out dates, epochs, booleans, lists and empty values', () => {
		const rows = Object.fromEntries(
			propRows({
				created_at: '2026-04-14T12:00:00Z',
				created_ts: 1776168000,
				is_bot: false,
				files: ['a.py', 'b.py'],
				labels: [],
				count: 1200,
				state: null
			}).map((r) => [r.key, r.value])
		);
		expect(rows.created_at).toBe(rows.created_ts);
		expect(rows.created_at).toContain('2026');
		expect(rows.is_bot).toBe('no');
		expect(rows.files).toBe('a.py, b.py');
		expect(rows.labels).toBe('—');
		expect(rows.count).toBe('1200');
		expect(rows.state).toBe('—');
	});

	it('cuts long text at a word and folds whitespace', () => {
		const [row] = propRows({ body: 'word '.repeat(100) + '\n\nend' }, 22);
		expect(row.value).toBe('word word word word …');
		expect(propRows(undefined)).toEqual([]);
	});
});
